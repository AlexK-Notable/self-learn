"""U-sdk acceptance criteria (docs/specs/self-learn/drafts/
u-sdk-backend-spec.md §4): SU/PL/OP/CH/KL/SY/OU/EV/RS/HG.

Every session in this file that actually drives `SdkBackend` sets
`SELF_LEARN_SDK_CLI_PATH` to `tests/fixtures/fake_claude.py` (via the
`sdk_cli_path` fixture) -- `HG2`. No test ever reaches the network or a
real model.

`sdk_absent` (`Sim-1`) is the ONE fixture `test_invocation.py`'s nine
amended tests import by name (`Sim-1a` forbids `autouse` here -- see
`SU6`'s fourth leg). It is defined ONCE, in this file.

Instrument-only criteria (`SU2`, `SU3`, `RS5`, `HG5`) and baseline/
anti-tamper criteria (`SU1`, `SU4`, `SU5`, `RS1`) have no test function
here, per §5.1's declared classes -- they are satisfied by command
output recorded in the build report / by the nine-amended-test diff
bound, not by a function.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.abc
import importlib.machinery
import inspect
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
)

from self_learn import provider as provider_mod
from self_learn import worker
from self_learn.invocation.contract import (
    DEGRADED_WORKER_CONTAINMENT,
    LOG_TEMPLATES,
    Containment,
    LogTemplates,
    Outcome,
    SessionSpec,
    containment_for,
)
from self_learn.invocation_sdk import SdkBackend, SdkOutcome
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from self_learn.invocation_sdk import events as events_mod
from self_learn.invocation_sdk import lifecycle as lifecycle_mod
from self_learn.invocation_sdk import provider_env as provider_env_mod

from test_worker import (  # noqa: F401 -- fixtures resolved by name
    Env,
    sdk_fake_worker,
    env,
    seed_pending,
)

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"

_INVOCATION_SDK_PREFIX = "self_learn.invocation_sdk"


# ===================================================================== #
# Shared fixtures
# ===================================================================== #


@pytest.fixture()
def sdk_absent(monkeypatch):
    """`Sim-1`/`Dep-1`/`RS2` -- simulates `claude_agent_sdk` being
    uninstalled in THIS process, WITHOUT ever uninstalling it. Evicts any
    already-imported `self_learn.invocation_sdk` package/submodules --
    otherwise `registry._resolve`'s lazy import would return the cached,
    already-successfully-built module regardless of the poison below,
    since a cached module is never re-executed -- and blocks a fresh
    `claude_agent_sdk` import. Both steps are `monkeypatch.setitem`/
    `delitem` on `sys.modules`, torn down automatically at test end.
    Blocks `claude_agent_sdk` and NOTHING else: an unrelated import
    still succeeds (`SU6` leg iii)."""
    for name in list(sys.modules):
        if name == _INVOCATION_SDK_PREFIX or name.startswith(_INVOCATION_SDK_PREFIX + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    yield


@pytest.fixture()
def sdk_cli_path(monkeypatch):
    """`HG2`/`FK-a` -- every session in this file is driven against the
    fake CLI, never a real one. `CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1`
    keeps the SDK from shelling out `<cli_path> -v`, which the fake does
    not implement."""
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    return FAKE_CLI


# ===================================================================== #
# Shared spec/containment builders
# ===================================================================== #

_WORKER_ALLOWED = "Read,Grep,Glob"
_WORKER_DISALLOWED = "Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"
_MINER_DISALLOWED = _WORKER_DISALLOWED + ",Read,Grep,Glob"
_ANALYST_ALLOWED = "Read,Grep,Glob"


# U-cleanup §7: `_worker_argv`/`_miner_argv`/`_analyst_argv` DELETED --
# they built the CLI-flavoured argv `_spec`'s deleted `cli_argv_builder`
# closed over. `_spec` now takes `doctrine` directly, matching
# `SessionSpec`'s first-class field.


def _containment(surface: str, *, home: Path, enforce: bool = True, write_exact: tuple[str, ...] = ()) -> Containment:
    if surface in ("worker", "worker-repair"):
        return containment_for(
            surface,
            allowed_tools=_WORKER_ALLOWED,
            disallowed_tools=_WORKER_DISALLOWED,
            home=str(home),
            stage_dir=home / "stage",
            stage_on=False,
            enforce=enforce,
            write_exact=write_exact,
        )
    if surface == "miner-reader":
        return containment_for(
            "miner-reader", disallowed_tools=_MINER_DISALLOWED, spool_dir=home / "spool"
        )
    if surface == "analyst":
        return containment_for("analyst", allowed_tools=_ANALYST_ALLOWED)
    raise ValueError(surface)


def _spec(
    surface: str,
    *,
    home: Path,
    prompt: str = "ok_text",
    timeout: float = 20.0,
    containment: Containment | None = None,
    log=None,
    label: str = "",
    timeout_display=None,
    doctrine: str | None = None,
) -> SessionSpec:
    if containment is None:
        containment = _containment(surface, home=home)
    return SessionSpec(
        surface=surface,
        prompt=prompt,
        cwd=home,
        timeout=timeout,
        containment=containment,
        log=log or (lambda _msg: None),
        label=label,
        timeout_display=timeout_display,
        doctrine=doctrine,
    )


def _run(spec: SessionSpec) -> SdkOutcome:
    outcome = SdkBackend().write_session(spec)
    assert isinstance(outcome, SdkOutcome)
    return outcome


def _run_text(spec: SessionSpec) -> SdkOutcome:
    outcome = SdkBackend().text_session(spec)
    assert isinstance(outcome, SdkOutcome)
    return outcome


# ===================================================================== #
# SU -- the suite (SU6 is the one criterion in this group with a function)
# ===================================================================== #


def _test_invocation_py_source() -> str:
    return (Path(__file__).parent / "test_invocation.py").read_text(encoding="utf-8")


#: U-cleanup-A (fold round, code gate r1 `8uvjHmdKaUd6PI3tSyB-F`, full-suite
#: re-run): `test_wr6_analyst_failure_mappings_are_byte_exact_and_rendered_
#: through_log_templates` DROPPED from this set. MAJOR-1's un-skip rebuilt
#: `wr6` as a multi-leg test that needs REAL `claude_agent_sdk` imports for
#: legs 1-3/5 (not-found/timeout/exit/mutated-templates) and an ABSENT sdk
#: for leg 4 (unavailable) -- in the SAME test function. Requesting the
#: shared `sdk_absent` fixture poisons `sys.modules["claude_agent_sdk"]`
#: for the WHOLE test (function-scoped monkeypatch, undone only at test
#: teardown), which broke every other leg when tried. `wr6`'s leg 4 instead
#: reimplements `sdk_absent`'s OWN safe mechanism inline -- a nested
#: `pytest.MonkeyPatch()` instance scoped to just that leg, with an explicit
#: `.undo()` in a `finally` block -- which is exactly what this test's own
#: leg (iii)/docstring cares about (restored via monkeypatch, never a raw
#: unrestored `del sys.modules[...]`); it just does not route through the
#: named fixture to get there. `wr2` stays in the set (single-leg, sdk_absent
#: for its whole body, no conflict).
_SIM_2_NINE = {
    "test_rg1_five_rung_precedence_resolves_in_isolation",
    "test_rg2_each_rung_shadows_the_ones_below",
    "test_rg4_sdk_raises_backend_unavailable_with_install_command",
    "test_rg5_write_session_returns_unavailable_without_raising",
    "test_rg5_text_session_returns_unavailable_without_raising",
    "test_rg5_analyst_analyze_converts_unavailable_to_analyst_error",
    "test_rg5_shimmed_worker_run_completes_under_sdk_selection",
    "test_wr2_miner_early_returns_precede_the_stray_sweep",
}


def test_su6_the_nine_request_the_fixture_and_it_is_singly_defined_and_scoped(monkeypatch):
    """`SU6` -- four legs. (i) each of the (now eight -- U-cleanup-A fold
    round dropped `wr6`, see `_SIM_2_NINE`'s own comment) names `sdk_absent`
    in its
    parameter list. (ii) the fixture is defined exactly once, in this
    file. (iii) it blocks `claude_agent_sdk` and no other module. (iv)
    this file defines no `autouse` fixture (`Sim-1a`).

    Leg (iii) mirrors `sdk_absent` itself via `monkeypatch` (not a raw,
    unrestored `del sys.modules[...]`) -- a manual delete here would
    permanently evict the already-imported `self_learn.invocation_sdk`
    package for the rest of THIS pytest session, so later tests (e.g.
    `RS2`/`RS6`) would reimport it fresh and compare a stale top-level
    `SdkBackend` reference against a structurally-identical-but-distinct
    class -- exactly the failure this fixture exists to prevent."""
    tree = ast.parse(_test_invocation_py_source(), filename="test_invocation.py")
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _SIM_2_NINE:
            seen.add(node.name)
            params = {a.arg for a in node.args.args}
            assert "sdk_absent" in params, f"{node.name} does not request sdk_absent"
    assert seen == _SIM_2_NINE, f"missing: {_SIM_2_NINE - seen}"

    # (ii) exactly one definition site, in THIS file.
    this_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=str(__file__))
    defs_here = [
        n for n in ast.walk(this_tree) if isinstance(n, ast.FunctionDef) and n.name == "sdk_absent"
    ]
    assert len(defs_here) == 1

    # (iii) blocks claude_agent_sdk and nothing else.
    import types

    marker = types.ModuleType("self_learn_test_unrelated_marker")
    monkeypatch.setitem(sys.modules, "self_learn_test_unrelated_marker", marker)
    for name in list(sys.modules):
        if name == _INVOCATION_SDK_PREFIX or name.startswith(_INVOCATION_SDK_PREFIX + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)

    import self_learn_test_unrelated_marker  # noqa: F401 - proves an unrelated import survives

    with pytest.raises(ImportError):
        import claude_agent_sdk  # noqa: F401

    # (iv) no autouse fixture defined in this file (`Sim-1a`).
    for node in ast.walk(this_tree):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                text = ast.dump(deco)
                if "fixture" in text and "autouse" in text:
                    # confirm it is not simply "autouse=False"
                    call = deco if isinstance(deco, ast.Call) else None
                    if call is not None:
                        for kw in call.keywords:
                            if kw.arg == "autouse":
                                assert not (
                                    isinstance(kw.value, ast.Constant) and kw.value.value is True
                                ), f"autouse fixture found: {node.name}"


# ===================================================================== #
# PL -- placement, imports, the re-covered guards
# ===================================================================== #


def test_pl1_package_contains_exactly_the_six_modules():
    pkg_dir = Path(backend_mod.__file__).resolve().parent
    names = {p.name for p in pkg_dir.glob("*.py")}
    assert names == {
        "__init__.py", "backend.py", "charter.py", "lifecycle.py", "events.py", "provider_env.py",
    }


_FORBIDDEN_IMPORTS = {"miner", "analyst", "verbs", "teach", "ledger_ops"}


def test_pl2_no_forbidden_imports_and_worker_use_is_scoped():
    pkg_dir = Path(backend_mod.__file__).resolve().parent
    worker_attrs: set[str] = set()
    for path in sorted(pkg_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    last = alias.name.split(".")[-1]
                    assert last not in _FORBIDDEN_IMPORTS, (path.name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                mod_last = mod.split(".")[-1] if mod else ""
                assert mod_last not in _FORBIDDEN_IMPORTS, (path.name, mod)
                for alias in node.names:
                    assert alias.name not in _FORBIDDEN_IMPORTS, (path.name, alias.name)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "worker":
                    worker_attrs.add(node.attr)
    assert worker_attrs <= {"cache_dir", "_pid_alive"}, worker_attrs


_FS_CALLS = {"open", "write_text", "mkdir", "unlink", "touch"}
_PL3_ALLOWED = {
    ("events.py", "write_text"), ("events.py", "unlink"), ("events.py", "mkdir"),
    ("lifecycle.py", "write_text"), ("lifecycle.py", "unlink"),
}


def test_pl3_filesystem_writes_are_enumerated_with_an_exact_count():
    pkg_dir = Path(backend_mod.__file__).resolve().parent
    violations = []
    for path in sorted(pkg_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name in _FS_CALLS:
                    violations.append((path.name, node.lineno, name))
    unexpected = [v for v in violations if (v[0], v[2]) not in _PL3_ALLOWED]
    assert unexpected == [], unexpected
    assert len(violations) == 5, violations


def test_pl4_every_written_path_resolves_under_cache_dir(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "pl4-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "pl4-xdg"))
    before = set((tmp_path / "pl4-xdg").rglob("*")) if (tmp_path / "pl4-xdg").is_dir() else set()
    spec = _spec("worker", home=home, prompt="ok_text")
    _run(spec)
    after = set((tmp_path / "pl4-xdg").rglob("*"))
    new_files = [p for p in (after - before) if p.is_file()]
    cache = worker.cache_dir()
    resolved_home = home.resolve()
    for p in new_files:
        rp = p.resolve()
        assert rp.is_relative_to(cache), rp
        assert not rp.is_relative_to(resolved_home), rp
        assert (Path(tmp_path) / ".git") not in rp.parents


def test_pl5_no_other_module_calls_write_session_or_text_session():
    src_dir = Path(worker.__file__).resolve().parent
    seam_funcs = {"write_session", "text_session"}
    sites: dict[str, list] = {}
    for path in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name in seam_funcs:
                    rel = str(path.relative_to(src_dir))
                    sites.setdefault(rel, []).append((node.lineno, name))
    assert set(sites) == {"worker.py", "miner.py", "analyst.py"}, sites


def test_pl6_fresh_interpreter_import_order_both_ways():
    env = dict(os.environ)
    src_root = str(Path(worker.__file__).resolve().parents[1])
    scripts = [
        "import self_learn.invocation_sdk",
        "import self_learn.worker; import self_learn.invocation_sdk",
        "import self_learn.invocation; import self_learn.invocation_sdk",
    ]
    for script in scripts:
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=src_root, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (script, result.stdout, result.stderr)


# ===================================================================== #
# OP -- the option set
# ===================================================================== #


def test_op1_query_is_never_called(tmp_path, sdk_cli_path, monkeypatch):
    import claude_agent_sdk

    def boom(*a, **kw):
        raise AssertionError("query() must never be called -- F-A")

    monkeypatch.setattr(claude_agent_sdk, "query", boom)
    home = tmp_path / "op1-home"
    home.mkdir()
    outcome = _run(_spec("worker", home=home, prompt="ok_text"))
    assert outcome.ok is True


def test_op2_allowed_tools_always_empty(tmp_path, sdk_cli_path):
    home = tmp_path / "op2-home"
    home.mkdir()
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        spec = _spec(surface, home=home)
        kwargs = backend_mod.options_kwargs(spec)
        assert kwargs["allowed_tools"] == [], surface


def test_op3_setting_sources_explicit_empty_list(tmp_path, sdk_cli_path):
    home = tmp_path / "op3-home"
    home.mkdir()
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        kwargs = backend_mod.options_kwargs(_spec(surface, home=home))
        assert kwargs["setting_sources"] == []
        assert kwargs["setting_sources"] is not None


def test_op4_settings_always_none(tmp_path, sdk_cli_path):
    """U-cleanup §7: `settings` is ALWAYS `None` (`A-2` -- the charter is
    the only authority) for every surface, unconditionally -- there is no
    settings writer left to call before it (§8.1: `write_reader_settings`
    deleted; nothing under the sdk backend ever wrote or read a settings
    file for any surface, including before this unit closed miner-
    reader's live residual, §2.3)."""
    home = tmp_path / "op4-home"
    home.mkdir()
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        kwargs = backend_mod.options_kwargs(_spec(surface, home=home))
        assert kwargs["settings"] is None, surface


def test_op5_permission_mode_always_default(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "op5-home"
    home.mkdir()
    for enforce in (True, False):
        for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
            containment = _containment(surface, home=home, enforce=enforce)
            kwargs = backend_mod.options_kwargs(_spec(surface, home=home, containment=containment))
            assert kwargs["permission_mode"] == "default", (surface, enforce)


def test_op6_strict_mcp_config_always_true(tmp_path, sdk_cli_path):
    home = tmp_path / "op6-home"
    home.mkdir()
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        kwargs = backend_mod.options_kwargs(_spec(surface, home=home))
        assert kwargs["strict_mcp_config"] is True
        assert kwargs["mcp_servers"] == {}


def test_op7_disallowed_tools_matches_containment_split_at_test_time(tmp_path, sdk_cli_path):
    home = tmp_path / "op7-home"
    home.mkdir()
    cases = {
        "worker": worker.DISALLOWED_TOOLS.split(","),
        "worker-repair": worker.DISALLOWED_TOOLS.split(","),
        "miner-reader": (worker.DISALLOWED_TOOLS + ",Read,Grep,Glob").split(","),
        "analyst": [],
    }
    for surface, expected in cases.items():
        kwargs = backend_mod.options_kwargs(_spec(surface, home=home))
        assert kwargs["disallowed_tools"] == expected, surface


def test_op8_max_turns_defaults_and_selector_overrides(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "op8-home"
    home.mkdir()
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_TURNS_WORKER", raising=False)
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_TURNS_MINER", raising=False)
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_TURNS_ANALYST", raising=False)
    assert backend_mod.options_kwargs(_spec("worker", home=home))["max_turns"] == 120
    assert backend_mod.options_kwargs(_spec("worker-repair", home=home))["max_turns"] == 120
    assert backend_mod.options_kwargs(_spec("miner-reader", home=home))["max_turns"] == 60
    assert backend_mod.options_kwargs(_spec("analyst", home=home))["max_turns"] == 30

    monkeypatch.setenv("SELF_LEARN_SDK_MAX_TURNS_WORKER", "7")
    assert backend_mod.options_kwargs(_spec("worker", home=home))["max_turns"] == 7
    assert backend_mod.options_kwargs(_spec("worker-repair", home=home))["max_turns"] == 7
    # WORKER's override does not leak into MINER's selector.
    assert backend_mod.options_kwargs(_spec("miner-reader", home=home))["max_turns"] == 60


def test_op9_max_budget_usd_default_none_env_override_and_feature_detection(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "op9-home"
    home.mkdir()
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_BUDGET_USD", raising=False)
    assert backend_mod.options_kwargs(_spec("worker", home=home))["max_budget_usd"] is None
    monkeypatch.setenv("SELF_LEARN_SDK_MAX_BUDGET_USD", "2.5")
    assert backend_mod.options_kwargs(_spec("worker", home=home))["max_budget_usd"] == 2.5
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_BUDGET_USD", raising=False)

    # feature detection: an unappliable cap degrades LOUDLY. `MAJOR-4`:
    # the `_dataclass_fields` stub is scoped to a NESTED `MonkeyPatch`
    # context (never `monkeypatch.undo()` on the shared, fixture-owned
    # instance -- `BLOCKER-1` -- since that would also revert
    # `sdk_cli_path`'s `SELF_LEARN_SDK_CLI_PATH`, which the `_run(...)`
    # below still needs).
    class _StubField:
        def __init__(self, name):
            self.name = name

    stub_fields = [_StubField(n) for n in ("cwd", "model")]  # neither max_* field present
    logs = []
    spec = _spec("worker", home=home, prompt="ok_text", log=logs.append)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(backend_mod, "_dataclass_fields", lambda _cls: stub_fields)
        kwargs = backend_mod.options_kwargs(spec)
        assert "max_turns" not in kwargs
        assert "max_budget_usd" not in kwargs
        # `MAJOR-4`: byte-exact, not a substring match.
        assert logs.count("run: sdk backend could not apply max_turns on this claude-agent-sdk version") == 1
        assert (
            logs.count("run: sdk backend could not apply max_budget_usd on this claude-agent-sdk version")
            == 1
        )
        # `MAJOR-4`'s third leg: the session still RUNS despite the
        # dropped caps -- asserted, not left as a comment.
        outcome = _run(spec)
        assert outcome.ok is True


def test_op10_system_prompt_never_none_and_analyst_appends(tmp_path, sdk_cli_path):
    home = tmp_path / "op10-home"
    home.mkdir()
    for surface in ("worker", "worker-repair", "miner-reader"):
        kwargs = backend_mod.options_kwargs(_spec(surface, home=home))
        assert kwargs["system_prompt"] is not None
        assert kwargs["system_prompt"] == {"type": "preset", "preset": "claude_code"}
    kwargs = backend_mod.options_kwargs(_spec("analyst", home=home, doctrine="DOCTRINE X"))
    assert kwargs["system_prompt"] is not None
    assert kwargs["system_prompt"] == {"type": "preset", "preset": "claude_code", "append": "DOCTRINE X"}


def test_op11_model_from_provider_unconditionally(tmp_path, sdk_cli_path):
    """`OP11`, restated by `U-bedrock`'s `IN3`/`Int-1`, then again by
    U-cleanup §7: `options.model` was never a relay of a `--model` argv
    element to begin with (`worker.build_argv` et al. were never
    provider-aware, `B-1`/§1.1) -- it is `provider.model_for(spec.surface,
    home=home)`, period, and after this unit there is no argv left to
    have carried a different value in the first place.

    U-cleanup §7 ALSO removes the second half this test used to carry:
    `_read_argv_flag`'s last-argv-element-with-no-value-after-it edge
    case (`A-4`, never an `IndexError`). That function is deleted --
    `options_kwargs` reads `spec.doctrine` directly now, so there is no
    argv shape left for an edge case to be about. `test_op13` is the
    surviving structural guard on the (now-empty) argv-literal read set."""
    home = tmp_path / "op11-home"
    home.mkdir()
    kwargs = backend_mod.options_kwargs(_spec("worker", home=home))
    assert kwargs["model"] == provider_mod.model_for("worker", home=home)


# U-cleanup-B DELETE: `test_op12_settings_writer_called_before_argv_
# builder` -- its subject (`cli_settings_writer`/`cli_argv_builder`'s
# ordering, `A-1`) no longer exists. `SessionSpec` carries neither field
# (§7); `options_kwargs` reads `spec.doctrine` directly, with no writer
# to call and no argv to build first.


def test_op13_argv_read_set_is_closed(tmp_path, sdk_cli_path):
    """`OP13`, re-baselined per §8.4b (a §7 consequence no earlier spec
    round named): `--append-system-prompt` was the LAST `--`-flag literal
    `options_kwargs` read out of an argv it built for exactly that
    purpose (`_read_argv_flag`, deleted, §7/`test_op11`). With the argv
    relay gone, this module contains no `--`-flag literal at all -- the
    closed read set is now the EMPTY set, and staying closed means
    `options_kwargs` reads `spec.doctrine` (a first-class field) and
    nothing argv-derived, ever again."""
    src = inspect.getsource(backend_mod)
    literals = set(re.findall(r'"(--[A-Za-z0-9-]+)"', src))
    assert literals == set(), literals


def test_op14_options_kwargs_matches_the_object_the_session_ran_on(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "op14-home"
    home.mkdir()
    expected_fields = {
        "cwd", "system_prompt", "model", "allowed_tools", "disallowed_tools", "can_use_tool",
        "permission_mode", "setting_sources", "settings", "strict_mcp_config", "mcp_servers",
        "include_partial_messages", "env", "cli_path", "max_turns", "max_budget_usd",
    }
    spec = _spec("worker", home=home, prompt="ok_text")
    kwargs = backend_mod.options_kwargs(spec)
    assert set(kwargs) == expected_fields

    captured = {}
    real_client_cls = ClaudeSDKClient

    class _Spy(real_client_cls):
        def __init__(self, *, options):
            captured["options"] = options
            super().__init__(options=options)

    monkeypatch.setattr(backend_mod, "ClaudeSDKClient", _Spy)
    outcome = _run(spec)
    assert outcome.ok is True
    options = captured["options"]
    for key, value in kwargs.items():
        actual = getattr(options, key)
        if key == "can_use_tool":
            assert callable(actual)
            continue
        assert actual == value, key


def test_op15_cli_path_from_env(tmp_path, monkeypatch):
    home = tmp_path / "op15-home"
    home.mkdir()
    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH", raising=False)
    kwargs = backend_mod.options_kwargs(_spec("worker", home=home))
    assert kwargs["cli_path"] is None
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    kwargs2 = backend_mod.options_kwargs(_spec("worker", home=home))
    assert kwargs2["cli_path"] == str(FAKE_CLI)


def test_op16_provider_env_called_exactly_once():
    pkg_dir = Path(backend_mod.__file__).resolve().parent
    count = 0
    for path in sorted(pkg_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name == "provider_env":
                    count += 1
    assert count == 1, count


def test_op17_options_env_is_empty_leak_test(tmp_path, sdk_cli_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("AWS_PROFILE", "not-a-real-profile")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    home = tmp_path / "op17-home"
    home.mkdir()
    for surface in ("worker", "worker-repair", "miner-reader", "analyst"):
        kwargs = backend_mod.options_kwargs(_spec(surface, home=home))
        assert kwargs["env"] == {}, surface


# ===================================================================== #
# CH -- the charter
# ===================================================================== #


class _Ctx:
    pass


def _call(cb, tool_name, tool_input):
    return asyncio.run(cb(tool_name, tool_input, _Ctx()))


def _worker_containment(home: Path, **kw) -> Containment:
    return containment_for(
        "worker", allowed_tools=_WORKER_ALLOWED, disallowed_tools=_WORKER_DISALLOWED,
        home=str(home), stage_dir=home / "stage", stage_on=False, **kw,
    )


def test_ch1_write_allowed_edit_denied_on_the_same_matching_path(tmp_path):
    home = tmp_path / "ch1-home"
    home.mkdir()
    target = home / "skills" / "s" / "proposals" / "x.yaml"
    cb = charter_mod.build_can_use_tool(_worker_containment(home, enforce=True))
    allow = _call(cb, "Write", {"file_path": str(target)})
    deny = _call(cb, "Edit", {"file_path": str(target)})
    assert isinstance(allow, PermissionResultAllow)
    assert isinstance(deny, PermissionResultDeny)


def test_ch2_deny_by_default_including_the_analyst_via_step_four(tmp_path):
    home = tmp_path / "ch2-home"
    home.mkdir()
    for tool in ("Bash", "Task", "WebFetch", "WebSearch", "NotebookEdit", "FutureTool"):
        cb = charter_mod.build_can_use_tool(_worker_containment(home, enforce=True))
        result = _call(cb, tool, {})
        assert isinstance(result, PermissionResultDeny), tool

    analyst_containment = containment_for("analyst", allowed_tools=_ANALYST_ALLOWED)
    cb_a = charter_mod.build_can_use_tool(analyst_containment)
    for tool in ("Bash", "Task", "WebFetch", "WebSearch", "NotebookEdit", "FutureTool"):
        result = _call(cb_a, tool, {})
        assert isinstance(result, PermissionResultDeny), tool


def test_ch3_write_with_no_resolvable_target_is_denied(tmp_path):
    home = tmp_path / "ch3-home"
    home.mkdir()
    cb = charter_mod.build_can_use_tool(_worker_containment(home, enforce=True))
    result = _call(cb, "Write", {})
    assert isinstance(result, PermissionResultDeny)
    assert "Write" in result.message


def test_ch4_leaf_symlink_on_write_exact_is_denied(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    target = real_dir / "a.txt"
    target.write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    evil = outside / "evil.txt"
    evil.write_text("y")
    target.unlink()
    target.symlink_to(evil)

    c = Containment(
        allowed_tools=None, disallowed_tools="Bash", write_globs=(), write_exact=(str(target),),
        strict_mcp=True, default_mode="default",
    )
    cb = charter_mod.build_can_use_tool(c)
    result = _call(cb, "Write", {"file_path": str(target)})
    assert isinstance(result, PermissionResultDeny)


def test_ch5_symlinked_parent_directory_still_allows_a_legitimate_write(tmp_path):
    real_home = tmp_path / "real_home"
    (real_home / "skills").mkdir(parents=True)
    link_home = tmp_path / "link_home"
    link_home.symlink_to(real_home)
    write_target = real_home / "skills" / "proposals" / "x.yaml"
    write_target.parent.mkdir(parents=True)
    write_target.write_text("z")

    c = Containment(
        allowed_tools=None, disallowed_tools="Bash",
        write_globs=(f"{link_home}/skills/**",), write_exact=(), strict_mcp=True, default_mode="default",
    )
    cb = charter_mod.build_can_use_tool(c)
    result = _call(cb, "Write", {"file_path": str(link_home / "skills" / "proposals" / "x.yaml")})
    assert isinstance(result, PermissionResultAllow)


def test_ch6_matcher_positive_and_negative_cases(tmp_path):
    home = tmp_path / "ch6-home"
    home.mkdir()
    c = Containment(
        allowed_tools=None, disallowed_tools="Bash",
        write_globs=(f"{home}/skills/**/proposals/**",), write_exact=(), strict_mcp=True, default_mode="default",
    )
    cb = charter_mod.build_can_use_tool(c)
    positive = [
        home / "skills" / "a" / "b" / "proposals" / "c" / "d.yaml",
        home / "skills" / "proposals" / "x.yaml",
        home / "skills" / "s1" / "proposals" / "y.diff",
        home / "skills" / "s1" / "s2" / "s3" / "proposals" / "z.yaml",
        home / "skills" / "proposals" / "sub" / "w.yaml",
    ]
    for p in positive:
        assert isinstance(_call(cb, "Write", {"file_path": str(p)}), PermissionResultAllow), p

    negative = [
        home / "skills" / "proposals-evil.yaml",
        home / "skills" / "proposals",
        home / "other" / "proposals" / "x.yaml",
        home / "skills-evil" / "a" / "proposals" / "x.yaml",
        home / "skills" / "a" / "proposals-evil" / "x.yaml",
    ]
    for p in negative:
        assert isinstance(_call(cb, "Write", {"file_path": str(p)}), PermissionResultDeny), p

    # `<stage>/**` -- inside the directory, never the directory itself.
    stage = tmp_path / "stage"
    stage.mkdir()
    c2 = Containment(
        allowed_tools=None, disallowed_tools="Bash", write_globs=(f"{stage}/**",), write_exact=(),
        strict_mcp=True, default_mode="default",
    )
    cb2 = charter_mod.build_can_use_tool(c2)
    assert isinstance(_call(cb2, "Write", {"file_path": str(stage / "x.yaml")}), PermissionResultAllow)
    assert isinstance(_call(cb2, "Write", {"file_path": str(stage)}), PermissionResultDeny)
    assert isinstance(
        _call(cb2, "Write", {"file_path": str(tmp_path / (stage.name + "-evil") / "x.yaml")}),
        PermissionResultDeny,
    )


@pytest.mark.parametrize("bad_char", ["[", "]", "{", "}"])
def test_ch7_unsupported_metacharacter_fails_closed_before_any_callback(tmp_path, bad_char, monkeypatch):
    home = tmp_path / "ch7-home"
    home.mkdir()
    c = Containment(
        allowed_tools=None, disallowed_tools="Bash",
        write_globs=(f"{home}/skills/{bad_char}a{bad_char}/**",), write_exact=(),
        strict_mcp=True, default_mode="default",
    )
    connected = []

    async def _spy_connect(self, *a, **kw):
        connected.append(1)

    monkeypatch.setattr(ClaudeSDKClient, "connect", _spy_connect)
    spec = _spec("worker", home=home, containment=c)
    outcome = _run(spec)
    assert outcome.ok is False
    assert outcome.failure == "os-error"
    assert connected == []


def test_ch8_four_deny_branches_are_distinct_and_name_the_tool(tmp_path):
    home = tmp_path / "ch8-home"
    home.mkdir()
    c = _worker_containment(home, enforce=True)
    cb = charter_mod.build_can_use_tool(c)
    d_deny = _call(cb, "Bash", {})
    no_target = _call(cb, "Write", {})
    mismatch = _call(cb, "Write", {"file_path": "/nowhere/x.md"})
    fallback = _call(cb, "WebSearch", {})
    messages = {d_deny.message, no_target.message, mismatch.message, fallback.message}
    assert len(messages) == 4
    for m in messages:
        assert m.startswith("self-learn invocation charter: ")
    assert "Bash" in d_deny.message
    assert "Write" in no_target.message
    assert "Write" in mismatch.message and "/nowhere/x.md" in mismatch.message
    assert "WebSearch" in fallback.message


def test_ch9_every_deny_is_recorded_in_the_sessions_denials(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "ch9-home"
    home.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(tmp_path / "outside.md"))
    c = _worker_containment(home, enforce=True)
    outcome = _run(_spec("worker", home=home, prompt="ok_write", containment=c))
    assert outcome.ok is True  # the SESSION completes; the WRITE was denied
    assert len(outcome.denials) == 1
    assert outcome.denials[0]["tool"] == "Write"

    monkeypatch.delenv("FAKE_CLAUDE_WRITE_TARGET", raising=False)
    outcome2 = _run(_spec("worker", home=home, prompt="ok_text", containment=c))
    assert outcome2.denials == ()


def test_ch10_hatch_open_driven_end_to_end_from_the_real_variable(env, sdk_fake_worker, monkeypatch, sdk_cli_path):
    """`CH10`'s headline leg -- `MAJOR-2` rebuild. Driven from the REAL
    `SELF_LEARN_ENFORCE_SCOPE` variable through a shimmed `worker.run`,
    observing the charter's ACTUAL verdict (a spy on
    `invocation.write_session` captures every `SdkOutcome`, real object,
    real `.denials`) rather than merely that a session completed. A real
    `worker.run()` prompt is long, dynamic and record-specific -- it can
    never match a `Fake-2` scenario key by equality -- so
    `FAKE_CLAUDE_FORCE_SCENARIO` (a test-fixture-only knob; see
    `fake_claude.py`) routes it to `ok_write` regardless of its exact
    text, letting the write actually reach the callback.

    `CH10`'s second leg (`Bash` still denied) and third leg
    (`worker-repair` opens too, `write_exact` not `write_globs`) stay as
    their own functions below, unit-testing `build_can_use_tool` directly
    against hand-built containments -- this leg is the one the criterion
    requires be driven from the real variable end to end."""
    from self_learn import invocation as invocation_mod

    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)
    # U-flip pins SELF_LEARN_BACKEND_WORKER=cli at rung 1 (conftest's
    # suite-wide default); clear it too, or it shadows this rung-2
    # override and worker never reaches the sdk transport.
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")  # write_permission_rules -- the ledger globs
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")  # keep this leg to the BATCH round only
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    outside = env.home.parent / "ch10-outside.md"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(outside))

    outcomes: list[SdkOutcome] = []
    real_write_session = invocation_mod.write_session

    def spy_write_session(spec, *, backend=None):
        outcome = real_write_session(spec, backend=backend)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(invocation_mod, "write_session", spy_write_session)

    # Leg (1a): hatch OPEN (`ENFORCE_SCOPE=0`) -- the out-of-glob write is
    # APPROVED by the REAL charter, reached through the REAL variable.
    seed_pending(env, rid="lrn-0000c10a")
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")
    outcomes.clear()
    result_open = worker.run(env.home)
    assert result_open is not None
    # U-cleanup-A: `sdk_fake_worker["count"]() == 0` used to prove
    # "the PATH shim's claude never ran -- the SDK path did" against a
    # BASH-backed fixture, where the count came from a wholly separate
    # counter than whatever the SDK path used. The migrated fixture is
    # itself sdk-backed now, sharing `fake_claude.py`'s own
    # `FAKE_CLAUDE_CALLS` counter with THIS test's own real worker.run()
    # call -- so the count is now legitimately >=1 the moment ANY sdk
    # invocation happens, this test's own included, and no longer
    # distinguishes "CLI ran" from "SDK ran". The positive proof that
    # this leg reached the sdk backend for real is `outcomes` itself
    # (below) -- a spy on `invocation.write_session` capturing a genuine
    # `SdkOutcome`, stronger evidence than the old CLI-shim-count proxy.
    assert outcomes, "worker.run never reached the sdk backend"
    assert outcomes[-1].denials == ()  # `MAJOR-2`: the charter's verdict, observed

    # Leg (1b): hatch CLOSED (`ENFORCE_SCOPE=1`) -- the SAME write,
    # through the SAME shimmed prompt, is DENIED by the SAME real charter.
    seed_pending(env, rid="lrn-0000c10b")
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "1")
    outcomes.clear()
    result_closed = worker.run(env.home)
    assert result_closed is not None
    # See leg (1a)'s comment above -- same rebase, same reason.
    assert outcomes, "worker.run never reached the sdk backend"
    assert len(outcomes[-1].denials) == 1
    assert outcomes[-1].denials[0]["tool"] == "Write"


def test_ch10_second_leg_bash_still_denied_under_the_hatch(tmp_path):
    home = tmp_path / "ch10b-home"
    home.mkdir()
    c_open = containment_for(
        "worker", allowed_tools=_WORKER_ALLOWED, disallowed_tools=_WORKER_DISALLOWED,
        home=str(home), stage_dir=home / "stage", stage_on=False, enforce=False,
    )
    cb = charter_mod.build_can_use_tool(c_open)
    assert isinstance(_call(cb, "Write", {"file_path": "/anywhere.md"}), PermissionResultAllow)
    assert isinstance(_call(cb, "Bash", {}), PermissionResultDeny)


def test_ch10_third_leg_worker_repair_opens_too(tmp_path):
    """`CH10`'s third leg / `MAJOR-3`: `worker-repair`'s containment
    carries its scope in `write_exact`, not `write_globs` -- the hatch's
    second conjunct must be the UNION of both (`M62`'s negative
    control)."""
    home = tmp_path / "ch10c-home"
    home.mkdir()
    repair_containment = containment_for(
        "worker-repair", allowed_tools=_WORKER_ALLOWED, disallowed_tools=_WORKER_DISALLOWED,
        write_exact=(str(home / "pending" / "lrn-x.md"),), enforce=False,
    )
    assert repair_containment.default_mode is None
    assert repair_containment.write_globs == ()
    assert repair_containment.write_exact != ()
    cb = charter_mod.build_can_use_tool(repair_containment)
    result = _call(cb, "Write", {"file_path": "/outside/anything.md"})
    assert isinstance(result, PermissionResultAllow)


def test_ch11_hatch_closed_four_legs():
    # (i) variable unset -> denied, byte-identical reason to the pre-hatch build.
    c_closed = Containment(
        allowed_tools=None, disallowed_tools="Bash", write_globs=("/tmp/ch11/**",), write_exact=(),
        strict_mcp=True, default_mode="default",
    )
    cb = charter_mod.build_can_use_tool(c_closed)
    result = _call(cb, "Write", {"file_path": "/outside.md"})
    assert isinstance(result, PermissionResultDeny)
    assert result.message == "self-learn invocation charter: Write write scope does not include /outside.md"

    # (ii) analyst containment (empty write sets) still denies the whole write family.
    c_analyst = containment_for("analyst", allowed_tools=_ANALYST_ALLOWED)
    assert c_analyst.default_mode is None
    cb_a = charter_mod.build_can_use_tool(c_analyst)
    assert isinstance(_call(cb_a, "Write", {"file_path": "/anywhere.md"}), PermissionResultDeny)

    # (iii) miner containment (default_mode == "default") still denies a write outside the spool.
    c_miner = containment_for("miner-reader", disallowed_tools=_MINER_DISALLOWED, spool_dir="/tmp/spool")
    cb_m = charter_mod.build_can_use_tool(c_miner)
    assert isinstance(_call(cb_m, "Write", {"file_path": "/outside/spool.txt"}), PermissionResultDeny)

    # (iv) DEGRADED_WORKER_CONTAINMENT grants nothing.
    cb_d = charter_mod.build_can_use_tool(DEGRADED_WORKER_CONTAINMENT)
    assert isinstance(_call(cb_d, "Write", {"file_path": "/anything.md"}), PermissionResultDeny)


def test_ch12_the_fence_hatch_changes_only_the_charter(tmp_path):
    home = tmp_path / "ch12-home"
    home.mkdir()
    for enforce in (True, False):
        kwargs = backend_mod.options_kwargs(
            _spec("worker", home=home, containment=_worker_containment(home, enforce=enforce))
        )
        assert kwargs["permission_mode"] == "default"
        assert kwargs["setting_sources"] == []
        assert kwargs["strict_mcp_config"] is True
        assert kwargs["settings"] is None
    on = backend_mod.options_kwargs(_spec("worker", home=home, containment=_worker_containment(home, enforce=True)))
    off = backend_mod.options_kwargs(_spec("worker", home=home, containment=_worker_containment(home, enforce=False)))
    assert on["disallowed_tools"] == off["disallowed_tools"]


def test_ch13_silence_parity_on_both_hatch_paths(env, sdk_fake_worker, monkeypatch, sdk_cli_path):
    # U-flip pins SELF_LEARN_BACKEND_WORKER=cli at rung 1 (conftest's
    # suite-wide default); clear it too, or it shadows this rung-2
    # override and worker never reaches the sdk transport.
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))

    seed_pending(env)
    for scope_value in ("0", "1"):
        logged.clear()
        monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", scope_value)
        worker.run(env.home)
        hatch_lines = [
            line for line in logged
            if "ENFORCE_SCOPE" in line or "enforce_scope" in line or "hatch" in line.lower()
        ]
        assert hatch_lines == [], (scope_value, logged)

    # source-level check: no log( call accompanies any _enforce_scope() site.
    src = inspect.getsource(worker)
    for line in src.splitlines():
        if "_enforce_scope()" in line:
            assert "log(" not in line


# ===================================================================== #
# KL -- the kill ladder and the child
# ===================================================================== #


def test_kl1_interrupt_is_bounded_and_the_ladder_stays_within_kill_secs(tmp_path, sdk_cli_path):
    home = tmp_path / "kl1-home"
    home.mkdir()

    async def _hanging_interrupt(self):
        await asyncio.sleep(3600)

    import claude_agent_sdk

    original = claude_agent_sdk.ClaudeSDKClient.interrupt
    claude_agent_sdk.ClaudeSDKClient.interrupt = _hanging_interrupt
    try:
        t0 = time.monotonic()
        outcome = _run(_spec("worker", home=home, prompt="hang", timeout=1.0))
        elapsed = time.monotonic() - t0
    finally:
        claude_agent_sdk.ClaudeSDKClient.interrupt = original
    assert outcome.failure == "timeout"
    margin = lifecycle_mod.INTERRUPT_GRACE_SECS + lifecycle_mod.KILL_SECS + 3.0
    assert elapsed <= 1.0 + margin, elapsed


def test_kl2_disconnect_is_shielded_the_task_survives_the_kill_bound(monkeypatch):
    """`KL2`, unit-tested directly against `run_kill_ladder` (not through
    the whole `SdkBackend`/fake-CLI stack, which cannot observe the task
    object or the strong-reference set from the outside). `BLOCKER-2`/
    `M25`: the stated assertions are on the TASK OBJECT itself -- still
    alive, not cancelled -- and on `_ABANDONED_DISCONNECTS` being
    non-empty at that moment; a mutant that awaits `disconnect()` with a
    plain `wait_for` (no `asyncio.shield`) gets its task CANCELLED by the
    timeout, which only these direct checks can see."""
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.05)

    class _Client:
        async def interrupt(self):
            return None

        async def disconnect(self):
            await asyncio.sleep(3600)

    async def _drive():
        client = _Client()
        before = set(lifecycle_mod._ABANDONED_DISCONNECTS)
        await lifecycle_mod.run_kill_ladder(client, None, lambda _m: None)
        added = lifecycle_mod._ABANDONED_DISCONNECTS - before
        assert len(added) == 1, "the abandoned disconnect() task was never tracked by a strong reference"
        task = next(iter(added))
        assert task.done() is False, "the shielded task must still be running at the kill bound"
        assert task.cancelled() is False, "a raw cancel pierced the SDK's own shielded escalation"
        # cleanup -- cancel + retrieve so nothing lingers for later tests.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())


def test_kl3_abandoned_task_is_discarded_and_logs_one_outcome_line(monkeypatch):
    """`KL3`, unit-tested directly. `BLOCKER-2`/`M26`: once the abandoned
    `disconnect()` task itself finishes, the strong reference must be
    DISCARDED from `_ABANDONED_DISCONNECTS` and exactly ONE line must
    name the outcome -- neither is observable through the whole-stack
    fake-CLI drive (`test_kl2...` above's old shared-function shape made
    both controls unobservable; split per the gate's NOTE-3)."""
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.02)

    class _Client:
        async def interrupt(self):
            return None

        async def disconnect(self):
            await asyncio.sleep(0.08)  # outlives the shrunk kill bound, then finishes cleanly

    async def _drive():
        logs: list[str] = []
        client = _Client()
        before = set(lifecycle_mod._ABANDONED_DISCONNECTS)
        await lifecycle_mod.run_kill_ladder(client, None, logs.append)
        added = lifecycle_mod._ABANDONED_DISCONNECTS - before
        assert len(added) == 1, "the abandoned disconnect() task was never tracked by a strong reference"
        task = next(iter(added))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except asyncio.CancelledError:
            pass  # an un-shielded mutant would have cancelled it -- let the done-callbacks run anyway
        await asyncio.sleep(0)  # done-callbacks are scheduled via call_soon; let them fire
        assert task not in lifecycle_mod._ABANDONED_DISCONNECTS, "the reference was never discarded"
        assert logs.count("run: sdk backend: abandoned disconnect() completed") == 1, logs

    asyncio.run(_drive())


def test_kl2_and_kl3_end_to_end_the_kill_bound_line_is_emitted(tmp_path, sdk_cli_path, monkeypatch):
    """Companion integration leg: the whole `SdkBackend` stack, driven
    against the fake CLI, still emits the kill-bound line and completes
    with `failure=='timeout'` -- the direct unit tests above are what
    prove the STATED assertions; this proves the wiring end to end."""
    home = tmp_path / "kl2-home"
    home.mkdir()

    async def _hanging_disconnect(self):
        await asyncio.sleep(3600)

    monkeypatch.setattr(ClaudeSDKClient, "disconnect", _hanging_disconnect)
    logs = []
    outcome = _run(_spec("worker", home=home, prompt="hang", timeout=1.0, log=logs.append))
    assert outcome.failure == "timeout"
    assert any("still running at the kill bound" in line for line in logs)


def test_kl_major1_disconnect_raising_is_distinguished_from_a_timeout(monkeypatch):
    """`MAJOR-1` -- `run_kill_ladder` ports `sdk.py:300-313`'s TWO
    branches: a `disconnect()` that RAISES immediately (never times out
    at all) must be reported by its OWN line and must NEVER be treated as
    a still-running background escalation. Mutation: collapse the two
    `except` branches back into one -- this test reddens."""
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 5.0)  # generous -- must NOT be reached

    class _Client:
        async def interrupt(self):
            return None

        async def disconnect(self):
            raise RuntimeError("boom-kl-major1")

    async def _drive():
        logs: list[str] = []
        client = _Client()
        before = set(lifecycle_mod._ABANDONED_DISCONNECTS)
        await lifecycle_mod.run_kill_ladder(client, None, logs.append)
        added = lifecycle_mod._ABANDONED_DISCONNECTS - before
        assert added == set(), "an immediately-raising disconnect() must not enter the abandoned set"
        assert logs == ["run: sdk backend: disconnect() raised: boom-kl-major1"], logs

    asyncio.run(_drive())


def test_kl4_hang_sigterm_ignored_child_is_gone_after_run_sync_returns(tmp_path, sdk_cli_path):
    home = tmp_path / "kl4-home"
    home.mkdir()
    cache_before = set()
    t0 = time.monotonic()
    outcome = _run(_spec("worker", home=home, prompt="hang_sigterm_ignored", timeout=2.0))
    elapsed = time.monotonic() - t0
    assert outcome.failure == "timeout"
    # bounded: interrupt grace + kill secs + slack, not the OS's own reap latency.
    assert elapsed <= 2.0 + lifecycle_mod.INTERRUPT_GRACE_SECS + lifecycle_mod.KILL_SECS + 5.0

    # `NOTE-14`: `pgrep -f fake_claude.py` is HOST-GLOBAL -- it matches
    # ANY process on the machine whose argv contains that literal
    # substring, including the gate's/this test's OWN shell command line
    # if it ever mentions the filename. The bracket-escape idiom
    # (`fake_clau[d]e.py`) makes the regex still match a real
    # `fake_claude.py` argv while no longer matching a command line that
    # merely QUOTES the pattern string itself.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        found = subprocess.run(
            ["pgrep", "-f", "fake_clau[d]e.py"], capture_output=True, text=True
        ).stdout.strip()
        if not found:
            break
        time.sleep(0.1)
    assert not found, f"fake_claude.py child(ren) still alive: {found}"


def test_kl5_getpgid_guard_via_recorders_no_real_signal(monkeypatch):
    calls = {"kill": [], "killpg": []}
    monkeypatch.setattr(lifecycle_mod.os, "kill", lambda pid, sig: calls["kill"].append((pid, sig)))
    monkeypatch.setattr(lifecycle_mod.os, "killpg", lambda pid, sig: calls["killpg"].append((pid, sig)))
    monkeypatch.setattr(lifecycle_mod.worker, "_pid_alive", lambda pid: True)

    monkeypatch.setattr(lifecycle_mod.os, "getpgid", lambda pid: 100)
    lifecycle_mod.kill_child(4242, lambda _m: None)
    assert calls["kill"] == [(4242, signal.SIGKILL)]
    assert calls["killpg"] == []

    calls["kill"].clear()
    monkeypatch.setattr(lifecycle_mod.os, "getpgid", lambda pid: 100 if pid == 0 else 200)
    lifecycle_mod.kill_child(4242, lambda _m: None)
    assert calls["killpg"] == [(4242, signal.SIGKILL)]
    assert calls["kill"] == []

    # swallowed exceptions
    def _raise_lookup(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(lifecycle_mod.os, "killpg", _raise_lookup)
    lifecycle_mod.kill_child(4242, lambda _m: None)  # must not raise

    def _raise_perm(pid, sig):
        raise PermissionError()

    monkeypatch.setattr(lifecycle_mod.os, "kill", _raise_perm)
    monkeypatch.setattr(lifecycle_mod.os, "getpgid", lambda pid: 100)
    lifecycle_mod.kill_child(4242, lambda _m: None)  # must not raise


def test_kl6_child_pid_of_is_defensive(monkeypatch):
    class _Good:
        class _Transport:
            class _Process:
                pid = 999
            _process = _Process()
        _transport = _Transport()

    assert lifecycle_mod.child_pid_of(_Good()) == 999

    class _Bad:
        pass

    assert lifecycle_mod.child_pid_of(_Bad()) is None

    class _WrongType:
        class _Transport:
            class _Process:
                pid = "not-an-int"
            _process = _Process()
        _transport = _Transport()

    # a non-AttributeError/TypeError failure isn't expected here; the
    # "wrong type" case still RETURNS whatever pid is (defensive walk,
    # not a type check) -- the criterion's actual failure mode is a
    # missing attribute, exercised by _Bad above.


def test_kl6_logs_the_byte_exact_line_once(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "kl6-home"
    home.mkdir()
    monkeypatch.setattr(lifecycle_mod, "child_pid_of", lambda client: None)
    logs = []
    outcome = _run(_spec("worker", home=home, prompt="ok_text", log=logs.append))
    assert outcome.ok is True
    matching = [line for line in logs if line == "run: sdk backend could not resolve the child pid"]
    assert len(matching) == 1, logs


def test_kl7_pid_sidecar_present_during_and_absent_after(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "kl7-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    seen_during = {}

    real_write = lifecycle_mod.write_sidecar

    def spy_write(surface, pid, cli):
        real_write(surface, pid, cli)
        seen_during["path_exists"] = lifecycle_mod._sidecar_path(surface).is_file()
        seen_during["content"] = json.loads(lifecycle_mod._sidecar_path(surface).read_text())

    monkeypatch.setattr(lifecycle_mod, "write_sidecar", spy_write)

    for prompt, expect_failure in (("ok_text", False), ("error_result", True), ("hang", True)):
        seen_during.clear()
        timeout = 1.0 if prompt == "hang" else 20.0
        outcome = _run(_spec("worker", home=home, prompt=prompt, timeout=timeout))
        assert seen_during.get("path_exists") is True, prompt
        assert {"pid", "started_at", "cli"} <= set(seen_during["content"])
        assert not lifecycle_mod._sidecar_path("worker").exists(), prompt


def test_kl8_orphan_sweep_kills_matching_and_spares_non_matching(tmp_path, sdk_cli_path, monkeypatch):
    """A shebang'd script's `/proc/<pid>/cmdline[0]` gets rewritten by
    the kernel to the INTERPRETER, not the script path -- so the
    "matches" leg uses a genuine native binary (a copy of `/bin/sleep`
    renamed to `claude`, no shebang indirection) whose cmdline[0] is
    exactly what was exec'd, honestly exercising the `basename ==
    "claude"` branch."""
    home = tmp_path / "kl8-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))

    real_sleep = subprocess.run(["which", "sleep"], capture_output=True, text=True).stdout.strip()
    claude_bin = tmp_path / "claude"
    import shutil as _shutil

    _shutil.copy(real_sleep, claude_bin)
    claude_bin.chmod(0o755)

    # leg 1: a sidecar-recorded pid whose /proc cmdline basename is
    # literally "claude" is killed.
    proc = subprocess.Popen([str(claude_bin), "60"])
    try:
        lifecycle_mod.write_sidecar("worker", proc.pid, str(claude_bin))
        sidecar = lifecycle_mod._sidecar_path("worker")
        data = json.loads(sidecar.read_text())
        data["started_at"] = 0.0  # force "older than this process"
        sidecar.write_text(json.dumps(data))
        logs = []
        lifecycle_mod.sweep_orphans("worker", logs.append)
        proc.wait(timeout=5)
        assert proc.returncode is not None
        assert not sidecar.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    # leg 2: a live sleeper whose cmdline does NOT match "claude" (nor
    # the sidecar's own recorded cli basename) is spared.
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        lifecycle_mod.write_sidecar("worker", sleeper.pid, str(claude_bin))
        sidecar = lifecycle_mod._sidecar_path("worker")
        data = json.loads(sidecar.read_text())
        data["started_at"] = 0.0
        sidecar.write_text(json.dumps(data))
        logs2 = []
        lifecycle_mod.sweep_orphans("worker", logs2.append)
        assert sleeper.poll() is None, "the non-matching sleeper must NOT be killed"
        assert not sidecar.exists()  # still cleared, per K-5
    finally:
        sleeper.kill()
        sleeper.wait()


# ===================================================================== #
# SY -- the sync bridge
# ===================================================================== #


def test_sy1_returns_the_coroutine_value_with_no_running_loop():
    async def _factory_body():
        return 42

    assert backend_mod.run_sync(lambda: _factory_body()) == 42


def test_sy2_and_sy4_runs_on_a_different_thread_when_a_loop_is_already_running():
    outer_thread = None
    inner_thread_id = []

    async def _factory_body():
        inner_thread_id.append(threading.get_ident())
        return "value"

    async def _caller():
        nonlocal outer_thread
        outer_thread = threading.get_ident()
        return backend_mod.run_sync(lambda: _factory_body())

    result = asyncio.run(_caller())
    assert result == "value"
    assert inner_thread_id[0] != outer_thread


def test_sy3_exception_propagates_with_original_type_both_branches():
    async def _raiser():
        raise OSError("boom-sy3")

    with pytest.raises(OSError, match="boom-sy3"):
        backend_mod.run_sync(lambda: _raiser())

    async def _caller():
        return backend_mod.run_sync(lambda: _raiser())

    with pytest.raises(OSError, match="boom-sy3"):
        asyncio.run(_caller())


def test_sy4_factory_called_exactly_once_inside_the_target_thread():
    calls = []

    async def _factory_body():
        calls.append(threading.get_ident())
        return None

    backend_mod.run_sync(lambda: _factory_body())
    assert len(calls) == 1
    assert calls[0] == threading.get_ident()  # no running loop -- same thread


def test_sy5_thread_is_non_daemon_and_joined_without_a_timeout():
    src = inspect.getsource(backend_mod.run_sync)
    assert "daemon=False" in src
    assert ".join()" in src

    started = threading.Event()
    finish_at = [None]

    async def _slow_factory():
        started.set()
        await asyncio.sleep(0.3)
        finish_at[0] = time.monotonic()
        return None

    async def _caller():
        t0 = time.monotonic()
        backend_mod.run_sync(lambda: _slow_factory())
        return time.monotonic() - t0

    elapsed = asyncio.run(_caller())
    assert elapsed >= 0.25  # run_sync did not return before the coroutine finished


# ===================================================================== #
# RO-6 -- U-cleanup-A's LOG_TEMPLATES byte-pin (T-TEMPLATES-BYTE-PINNED)
# ===================================================================== #


def test_templates_byte_pinned_ro6():
    """U-cleanup-A `CV3`/`RO-6` (`T-TEMPLATES-BYTE-PINNED`). Byte-pins
    every row of all three `LOG_TEMPLATES` sets (`worker` ==
    `worker-repair`, `miner-reader`, `analyst`) to the values captured at
    self-learn master `ed1882f` (2026-08-24) via a direct import of
    `LOG_TEMPLATES` -- WHILE `CliBackend` still existed and was still
    verified against by `test_worker_contract.py::
    test_fl2_byte_identity_and_provenance[sdk]`'s now-deleted
    `cli_line == sdk_line` comparison (spec `docs/specs/self-learn/drafts/
    u-cleanup-cli-path-removal-spec.md` S3.4.1/S3.4). This test IS that
    comparison's replacement: broader (every row of all three tables, not
    the three kinds `fl2[sdk]` covered on one table), and independent of a
    second transport existing to compare against. It ALSO replaces
    `test_ou3`'s dying `worker.not_found`-only byte-pin (S3.4's table).
    `M-9` (mutate one character of any template) must redden this test --
    it is the ONLY detector: `test_ou3`'s surviving `setitem` leg mutates
    the table itself at runtime, so a mutated SHIPPED table still "changes
    the emitted line" there and stays green regardless."""
    assert LOG_TEMPLATES["worker"] == LogTemplates(
        exited="run: {label}claude exited {rc}: {detail}",
        timed_out="run: {label}claude timed out after {timeout:g}s",
        not_found="run: {label}claude CLI not found on PATH",
        os_error="run: {label}claude invocation failed ({exc})",
        unavailable="run: {label}invocation backend unavailable ({exc})",
        detail_cap=400,
        detail_strip=False,
    )
    # worker-repair shares the worker table object (contract.py `L-a`) --
    # pinning identity, not just equality, catches a future split too.
    assert LOG_TEMPLATES["worker-repair"] is LOG_TEMPLATES["worker"]
    assert LOG_TEMPLATES["miner-reader"] == LogTemplates(
        exited="run: claude exited {rc}: {detail}",
        timed_out="run: claude timed out after {timeout}s",
        not_found="run: claude CLI not found on PATH",
        os_error="run: reader invocation failed ({exc})",
        unavailable="run: invocation backend unavailable ({exc})",
        detail_cap=400,
        detail_strip=False,
    )
    assert LOG_TEMPLATES["analyst"] == LogTemplates(
        exited="analyst exited {rc}: {detail}",
        timed_out="analyst timed out after {timeout:g}s",
        not_found="claude CLI not found on PATH",
        os_error="analyst invocation failed ({exc})",
        unavailable="invocation backend unavailable ({exc})",
        detail_cap=None,
        detail_strip=True,
    )


# ===================================================================== #
# RO-1..RO-4 -- fake_claude.py's per-invocation capture and the
# bash-shim-script interpreter (U-cleanup-A CV5)
# ===================================================================== #


def test_fake_argv_per_call_ro1(tmp_path, sdk_cli_path, monkeypatch):
    """RO-1/CV5 (`T-FAKE-ARGV-PER-CALL`): two invocations, two argv
    records. `FAKE_CLAUDE_CALLS_DIR/argv.<n>` is PER-CALL -- unlike the
    legacy `FAKE_CLAUDE_ARGV_LOG` (opens `"w"`, truncates every call and
    therefore only ever represents the LAST invocation), a second
    invocation's file does not erase the first's."""
    home = tmp_path / "ro1-home"
    home.mkdir()
    calls_dir = tmp_path / "calls"
    monkeypatch.setenv("FAKE_CLAUDE_CALLS_DIR", str(calls_dir))
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(tmp_path / "ro1-counter"))
    _run(_spec("worker", home=home, prompt="ok_text"))
    _run(_spec("worker", home=home, prompt="ok_text"))
    argv1_path, argv2_path = calls_dir / "argv.1", calls_dir / "argv.2"
    assert argv1_path.exists() and argv2_path.exists()
    argv1 = argv1_path.read_text(encoding="utf-8").split("\0")[:-1]
    argv2 = argv2_path.read_text(encoding="utf-8").split("\0")[:-1]
    assert argv1 and argv2  # both real, non-empty argv records, captured independently


def test_fake_prompt_log_ro2(tmp_path, sdk_cli_path, monkeypatch):
    """RO-2/CV5 (`T-FAKE-PROMPT-LOG`): per-invocation prompt capture --
    the exact wire-level `content` string each invocation received,
    distinguishable call to call (the bash shim's `prompt.$N`
    counterpart; T1's `FakeBackend.prompts` covers the seam but not the
    wire)."""
    home = tmp_path / "ro2-home"
    home.mkdir()
    calls_dir = tmp_path / "calls"
    monkeypatch.setenv("FAKE_CLAUDE_CALLS_DIR", str(calls_dir))
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(tmp_path / "ro2-counter"))
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_text")
    _run(_spec("worker", home=home, prompt="PROMPT-ONE"))
    _run(_spec("worker", home=home, prompt="PROMPT-TWO"))
    assert (calls_dir / "prompt.1").read_text(encoding="utf-8") == "PROMPT-ONE"
    assert (calls_dir / "prompt.2").read_text(encoding="utf-8") == "PROMPT-TWO"


def test_fake_multi_write_ro3(tmp_path, sdk_cli_path, monkeypatch):
    """RO-3/CV5 (`T-FAKE-MULTI-WRITE`): a `shim_script` scenario staging
    TWO heredoc writes (`CLAUDE_SHIM_SCRIPT`, the same bash idiom
    `test_worker.shim_writes`/`test_repair._write_script` emit,
    concatenated by `\\n` -- the shape `f"{good}\\n{bad}"`-style call
    sites actually build) lands BOTH target files in one invocation --
    `CLAUDE_SHIM_SCRIPT` is used at ~180 sites across 9 files and its
    dominant use is writing several proposal files in one turn."""
    home = tmp_path / "ro3-home"
    home.mkdir()
    target_a = home / "skills" / "s" / "proposals" / "a.yaml"
    target_b = home / "skills" / "s" / "proposals" / "b.yaml"
    script = (
        f"mkdir -p {target_a.parent} && cat > {target_a} <<'YAML'\ncontent-a\nYAML\n"
        f"mkdir -p {target_b.parent} && cat > {target_b} <<'YAML'\ncontent-b\nYAML"
    )
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", script)
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "shim_script")
    c = _containment("worker", home=home)
    outcome = _run(_spec("worker", home=home, prompt="shim_script", containment=c))
    assert outcome.ok is True, outcome
    assert target_a.read_text(encoding="utf-8") == "content-a\n"
    assert target_b.read_text(encoding="utf-8") == "content-b\n"


def test_fake_per_call_error_ro4(tmp_path, sdk_cli_path, monkeypatch):
    """RO-4/CV5 (`T-FAKE-PER-CALL-ERROR`): round 1 clean, round 2 error --
    the `CLAUDE_SHIM_EXIT_<n>` selector (falling back to the unnumbered
    `CLAUDE_SHIM_EXIT`, default 0) drives the round-2-fails-round-1-
    succeeds shape `test_repair.py`'s repair tests need, with the SAME
    per-invocation counter `RO-1`/`RO-3` share."""
    home = tmp_path / "ro4-home"
    home.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(tmp_path / "ro4-counter"))
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "shim_script")
    monkeypatch.delenv("CLAUDE_SHIM_SCRIPT", raising=False)
    monkeypatch.setenv("CLAUDE_SHIM_EXIT_2", "1")
    c = _containment("worker", home=home)
    outcome1 = _run(_spec("worker", home=home, prompt="shim_script", containment=c))
    assert outcome1.ok is True, outcome1
    outcome2 = _run(_spec("worker", home=home, prompt="shim_script", containment=c))
    assert outcome2.ok is False
    assert outcome2.failure == "exit"


# ===================================================================== #
# OU -- the outcome mapping
# ===================================================================== #


def test_ou1_every_row_of_the_map_1_table(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "ou1-home"
    home.mkdir()

    # ResultMessage, is_error=False
    o = _run(_spec("worker", home=home, prompt="ok_text"))
    assert (o.ok, o.rc, o.detail, o.failure) == (True, 0, "", None)

    # ResultMessage, is_error=True
    o2 = _run(_spec("worker", home=home, prompt="error_result"))
    assert (o2.ok, o2.rc, o2.failure) == (False, 1, "exit")
    assert o2.detail == "boom"

    # stream ended with no ResultMessage
    o3 = _run(_spec("worker", home=home, prompt="no_result", timeout=5.0))
    assert (o3.ok, o3.rc, o3.stdout, o3.failure) == (False, 1, "", "exit")
    assert o3.detail == "sdk session ended without a result"

    # CLINotFoundError
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/nonexistent/claude-fake")
    o4 = _run(_spec("worker", home=home, prompt="ok_text"))
    assert (o4.ok, o4.rc, o4.stdout, o4.detail, o4.failure) == (False, None, "", "", "not-found")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))

    # asyncio.TimeoutError from the wall-clock guard
    o5 = _run(_spec("worker", home=home, prompt="hang", timeout=1.0))
    assert (o5.ok, o5.rc, o5.stdout, o5.detail, o5.failure) == (False, None, "", "", "timeout")

    # CharterPatternUnsupported
    c_bad = Containment(
        allowed_tools=None, disallowed_tools="Bash", write_globs=("/tmp/[x]/**",), write_exact=(),
        strict_mcp=True, default_mode="default",
    )
    o6 = _run(_spec("worker", home=home, prompt="ok_text", containment=c_bad))
    assert o6.ok is False
    assert o6.rc is None
    assert o6.failure == "os-error"

    # bare OSError -- worker (caught) vs analyst (re-raised)
    # U-sdka Err-1 (FW-87): the analyst leg is now caught too -- see the
    # inverted sub-leg below.
    import claude_agent_sdk

    async def _os_err(self):
        raise OSError("transport blew up")

    original_connect = claude_agent_sdk.ClaudeSDKClient.connect
    monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", _os_err)
    try:
        o7 = _run(_spec("worker", home=home, prompt="ok_text"))
        assert (o7.ok, o7.rc, o7.stdout, o7.failure) == (False, None, "", "os-error")
        assert o7.detail == "transport blew up"

        o7a = _run_text(_spec("analyst", home=home, prompt="ok_text"))
        assert (o7a.ok, o7a.rc, o7a.stdout, o7a.failure) == (False, None, "", "os-error")
        assert o7a.detail == "transport blew up"
    finally:
        monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", original_connect)

    # ProcessError (nonzero CLI exit) -- driven via `hard_exit`.
    o8 = _run(_spec("worker", home=home, prompt="hard_exit", timeout=10.0))
    assert o8.ok is False
    assert o8.failure == "exit"
    assert o8.rc is not None

    # `MAJOR-3`: a genuine programming bug inside the drain (NOT the SDK's
    # wrapped-ProcessError shape) must PROPAGATE, not be rendered to the
    # operator as a fake "claude exited N" line.
    def _boom_add_tool_use(self, *a, **kw):
        raise AttributeError("boom-major3")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(events_mod.EventLog, "add_tool_use", _boom_add_tool_use)
        with pytest.raises(AttributeError, match="boom-major3"):
            _run(_spec("worker", home=home, prompt="ok_write"))


def test_ou2_rc_synthetic_one_and_none_by_failure_kind(tmp_path, sdk_cli_path):
    home = tmp_path / "ou2-home"
    home.mkdir()
    o = _run(_spec("worker", home=home, prompt="error_result"))
    assert o.rc == 1
    for prompt, timeout in (("hang", 1.0),):
        o2 = _run(_spec("worker", home=home, prompt=prompt, timeout=timeout))
        assert o2.rc is None


def test_ou3_sdk_not_found_wording_and_template_table_authority(tmp_path, sdk_cli_path, monkeypatch):
    """U-cleanup-A `CV3` (`T-SDK-NOT-FOUND-WORDING`). Formerly
    `test_ou3_failure_legs_render_byte_identical_to_clibackend_and_respect_the_template_table`:
    its first leg drove a REAL `CliBackend` (`CliBackend().write_session`)
    to pin `LOG_TEMPLATES["worker"].not_found`'s wording through the CLI
    transport -- that leg is DELETED here because it reaches
    `CliBackend._run`, which `AG1`'s tripwire forbids for the whole
    suite. The wording it pinned is re-asserted below through the SDK's
    OWN not-found leg (`CLINotFoundError` -> `invocation_sdk/backend.py`
    `:465-467`, which renders the SAME `LOG_TEMPLATES[surface].not_found`
    template `spec.log()`-side) -- `not-found` stays reachable under sdk
    (`test_ou1`'s `o4`, `:1491-1494` above) and this test extends that
    existing SHAPE assertion to a WORDING assertion. The table-authority
    leg below (the `setitem` mutation) is UNCHANGED from the original
    `test_ou3` -- it does not touch `CliBackend` and needed no rewrite."""
    home = tmp_path / "ou3-home"
    home.mkdir()

    sdk_logs = []
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/nonexistent/claude-fake")
    _run(_spec("worker", home=home, prompt="ok_text", log=sdk_logs.append))
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    assert sdk_logs and sdk_logs[0] == "run: claude CLI not found on PATH"

    # setitem on LOG_TEMPLATES must change the emitted line -- OU3's
    # second leg (own literals would NOT change here).
    original = LOG_TEMPLATES["worker"]
    import dataclasses as _dc

    mutated = _dc.replace(original, exited="MUTATED EXIT {rc} {detail}")
    logs2 = []

    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setitem(LOG_TEMPLATES, "worker", mutated)
    try:
        _run(_spec("worker", home=home, prompt="error_result", log=logs2.append))
    finally:
        mp.undo()
    assert any(line.startswith("MUTATED EXIT") for line in logs2)


def test_ou4_clean_session_silent_degradation_lines_only_when_forced(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "ou4-home"
    home.mkdir()
    clean_logs = []
    o = _run(_spec("worker", home=home, prompt="ok_text", log=clean_logs.append))
    assert o.ok is True
    assert clean_logs == []

    # `MAJOR-5`/`M57`: a clean session is clean regardless of the
    # enforcement hatch -- `O-quiet`'s silence is not conditioned on
    # `enforce=True`. Without this leg, M57 (the hatch logging a line
    # when it opens) was invisible to OU4 -- every other leg here drives
    # the DEFAULT (`enforce=True`, hatch-closed) containment, so the
    # hatch never actually opens anywhere in this test.
    hatch_logs = []
    hatch_containment = _worker_containment(home, enforce=False)
    o_hatch = _run(
        _spec("worker", home=home, prompt="ok_text", containment=hatch_containment, log=hatch_logs.append)
    )
    assert o_hatch.ok is True
    assert hatch_logs == []

    # `BLOCKER-1`: `monkeypatch.undo()` on the SHARED, fixture-owned
    # instance also reverts `sdk_cli_path`'s `SELF_LEARN_SDK_CLI_PATH` --
    # the very next `_run(...)` would then resolve a REAL, credentialed
    # session. Each stub below is scoped to its own nested
    # `pytest.MonkeyPatch()` context instead.
    cap_logs = []

    class _StubField:
        def __init__(self, name):
            self.name = name

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            backend_mod, "_dataclass_fields", lambda _cls: [_StubField("cwd"), _StubField("model")]
        )
        _run(_spec("worker", home=home, prompt="ok_text", log=cap_logs.append))
    assert any("could not apply" in line for line in cap_logs)

    pid_logs = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(lifecycle_mod, "child_pid_of", lambda client: None)
        _run(_spec("worker", home=home, prompt="ok_text", log=pid_logs.append))
    assert any("could not resolve the child pid" in line for line in pid_logs)


def test_ou5_bare_oserror_caught_on_worker_miner_and_analyst(tmp_path, sdk_cli_path, monkeypatch):
    import claude_agent_sdk

    async def _os_err(self):
        raise OSError("boom-ou5")

    monkeypatch.setattr(claude_agent_sdk.ClaudeSDKClient, "connect", _os_err)
    home = tmp_path / "ou5-home"
    home.mkdir()

    o_worker = _run(_spec("worker", home=home, prompt="ok_text"))
    assert o_worker.failure == "os-error"

    o_miner = _run(_spec("miner-reader", home=home, prompt="ok_text"))
    assert o_miner.failure == "os-error"

    # U-sdka Err-1 (FW-87): the preserved defect (R-1/T-c) is retired --
    # a bare OSError is now caught on the analyst leg too, `analyst.analyze`
    # and `text_session` included.
    o_analyst = _run_text(_spec("analyst", home=home, prompt="ok_text"))
    assert o_analyst.failure == "os-error"
    assert o_analyst.detail == "boom-ou5"


def test_ou6_analyst_text_extraction_both_branches(tmp_path, sdk_cli_path):
    home = tmp_path / "ou6-home"
    home.mkdir()
    # `M41`: branch 1 (`ResultMessage.result`) must win over branch 2 (the
    # final `AssistantMessage`'s text) -- `ok_text`'s two sentinels are
    # deliberately DIFFERENT strings, so a mutant that swaps the branch
    # order (prefers the assistant text) reddens this assertion.
    o1 = _run_text(_spec("analyst", home=home, prompt="ok_text"))
    assert o1.stdout == "RESULT-SENTINEL"

    o2 = _run_text(_spec("analyst", home=home, prompt="ok_blocks_only"))
    assert o2.stdout == "Hello from blocks"


def test_ou7_stdout_per_surface(tmp_path, sdk_cli_path):
    home = tmp_path / "ou7-home"
    home.mkdir()
    o_worker = _run(_spec("worker", home=home, prompt="ok_text"))
    assert o_worker.stdout == ""
    o_repair = _run(_spec("worker-repair", home=home, prompt="ok_text"))
    assert o_repair.stdout == ""
    o_miner = _run(_spec("miner-reader", home=home, prompt="ok_text"))
    assert o_miner.stdout == "RESULT-SENTINEL"
    o_analyst = _run_text(_spec("analyst", home=home, prompt="ok_text"))
    assert o_analyst.stdout == "RESULT-SENTINEL"


def test_ou8_unknown_message_type_mid_stream_is_skipped(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "ou8-home"
    home.mkdir()
    # Leg 1: the fake CLI's `malformed_line` scenario exercises a
    # non-JSON line the SDK's own TRANSPORT skips before any message
    # object is ever built -- `_run_session`'s drain never sees it at
    # all, so this leg alone cannot exercise `O-drain`.
    o = _run(_spec("worker", home=home, prompt="malformed_line"))
    assert o.ok is True

    # Leg 2 (`M42`): a `stream_event` line the SDK parses into a REAL
    # `StreamEvent` object, which `client.receive_response()` forwards to
    # OUR drain like any other message ahead of the terminating
    # `ResultMessage` -- this is what "every other message type is
    # tolerated by skipping" (`O-drain`) actually means, and it is the
    # leg a drain-raises mutant reddens.
    o2 = _run(_spec("worker", home=home, prompt="unknown_message_type"))
    assert o2.ok is True


# ===================================================================== #
# EV -- capture
# ===================================================================== #


def test_ev1_sdkoutcome_is_a_frozen_outcome_subclass_with_the_invariant():
    o = SdkOutcome(ok=True, rc=0, stdout="", detail="", failure=None)
    assert isinstance(o, Outcome)
    with pytest.raises(Exception):
        o.ok = False  # frozen
    with pytest.raises(ValueError):
        SdkOutcome(ok=True, rc=0, stdout="", detail="", failure="exit")


def test_ev2_tool_events_and_both_denial_sources(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "ev2-home"
    home.mkdir()
    o = _run(_spec("worker", home=home, prompt="ok_write"))
    kinds = {e["kind"] for e in o.tool_events}
    assert kinds == {"tool_use", "tool_result"}
    assert o.turns == 1
    assert o.session_id == "fake-session-1"
    assert o.cost_usd == 0.001

    o_clean = _run(_spec("worker", home=home, prompt="ok_text"))
    assert o_clean.turns == 1
    assert o_clean.session_id == "fake-session-1"


def test_ev3_jsonl_written_at_the_right_path_with_meta_and_survives_a_timeout(tmp_path, sdk_cli_path, monkeypatch):
    home = tmp_path / "ev3-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _run(_spec("worker", home=home, prompt="ok_text"))
    matches = list(worker.cache_dir().glob("worker.tool-events.*.jsonl"))
    assert len(matches) == 1
    name = matches[0].name
    run_id_part = name[len("worker.tool-events.") : -len(".jsonl")]
    assert re.match(r"^\d{8}T\d{6}Z-\d+$", run_id_part)
    lines = matches[0].read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])
    assert meta["type"] == "meta"
    assert meta["session_id"] == "fake-session-1"

    for f in worker.cache_dir().glob("worker.tool-events.*.jsonl"):
        f.unlink()
    _run(_spec("worker", home=home, prompt="hang", timeout=1.0))
    matches2 = list(worker.cache_dir().glob("worker.tool-events.*.jsonl"))
    assert len(matches2) == 1  # exists after a TIMED-OUT session too


def test_ev4_nothing_in_the_package_reads_a_tool_events_file():
    pkg_dir = Path(backend_mod.__file__).resolve().parent
    for path in sorted(pkg_dir.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "tool-events" not in src or path.name == "events.py", path.name
        if path.name == "events.py":
            assert ".glob(" in src  # the ONLY reference is the write/prune's own glob pattern
            assert "read_text" not in src  # never reads one back


def _ev5_seed_and_prune(tmp_path, monkeypatch):
    """Shared setup for `EV5`/`EV6` -- 20 aged `worker.tool-events.*`
    files plus three decoys, then one `prune_event_logs("worker")` call.
    `NOTE-3`: `EV5` and `EV6` used to share ONE test function, which made
    the spec's "X reddens while Y stays green" controls for `M34`/`M63`
    unobservable (one assertion failing failed both criteria) -- split
    into two functions below, each calling this same setup."""
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "ev5-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "ev5-xdg"))
    (tmp_path / "ev5-home").mkdir()
    cache = worker.cache_dir()
    monkeypatch.setenv("SELF_LEARN_SDK_EVENT_LOGS", "5")

    for i in range(20):
        p = cache / f"worker.tool-events.2026010{i%9}T00000{i}Z-1.jsonl"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (i, i))

    # decoy files -- must survive.
    decoys = [cache / "worker.log", cache / "worker.window", cache / "miner.tool-events.20260101T000000Z-1.jsonl"]
    for d in decoys:
        d.write_text("x", encoding="utf-8")
    # `NOTE-16`: the miner decoy's mtime must be OLDER than the 20 worker
    # files (aged 0-19 above), not "now" -- otherwise a widened `*.jsonl`
    # prune mutant (`M34`) sorts the decoy as NEWEST and deletes a 5th
    # worker file instead, which flips the control's direction (reddens
    # EV5, not EV6). Aging it to the epoch makes it the widened prune's
    # FIRST victim, as the criterion intends.
    os.utime(decoys[-1], (0, 0))

    events_mod.prune_event_logs("worker")
    return cache, decoys


def test_ev5_retention_keeps_only_the_newest_n(tmp_path, monkeypatch):
    cache, _decoys = _ev5_seed_and_prune(tmp_path, monkeypatch)
    remaining = sorted(cache.glob("worker.tool-events.*.jsonl"))
    assert len(remaining) == 5  # newest 5 kept


def test_ev6_prune_never_touches_another_surfaces_files_or_the_logs(tmp_path, monkeypatch):
    _cache, decoys = _ev5_seed_and_prune(tmp_path, monkeypatch)
    for d in decoys:
        assert d.is_file(), d  # negative control -- unaffected by "worker"'s prune


# ===================================================================== #
# RS -- the registry
# ===================================================================== #


def test_rs2_present_resolves_absent_raises_byte_identical_unavailable(tmp_path, monkeypatch, sdk_absent):
    from self_learn import invocation

    # U-flip pins SELF_LEARN_BACKEND_WORKER=cli at rung 1 (conftest's
    # suite-wide default); clear it too, or it shadows this rung-2
    # override.
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    with pytest.raises(invocation.BackendUnavailable) as exc_info:
        invocation.backend_for("worker", home=tmp_path)
    msg = (
        'the "sdk" invocation backend is not built yet — install it with:\n'
        "    pip install 'self-learn-cli[sdk]'"
    )
    assert str(exc_info.value) == msg
    assert isinstance(exc_info.value.__cause__, ImportError)


def test_rs2_present_returns_sdkbackend_for_every_surface(tmp_path, monkeypatch):
    # U-sdka `Pin-1`: conftest pins SELF_LEARN_BACKEND_ANALYST=cli at RUNG
    # 1, which shadows this test's rung-2 SELF_LEARN_BACKEND=sdk for the
    # analyst surface. This test is ABOUT rung 2 reaching every surface,
    # so it clears rung 1 first. The pin's one and only rung-2 casualty
    # (`E13`'s census). U-flip added matching rung-1 pins for
    # SELF_LEARN_BACKEND_WORKER/_MINER -- clear all three selectors.
    for var in ("SELF_LEARN_BACKEND_WORKER", "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST"):
        monkeypatch.delenv(var, raising=False)
    from self_learn import invocation

    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    for surface in invocation.SURFACES:
        backend = invocation.backend_for(surface, home=tmp_path)
        assert isinstance(backend, SdkBackend)


def test_rs3_importing_invocation_does_not_import_claude_agent_sdk():
    script = "import sys; import self_learn.invocation; assert 'claude_agent_sdk' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_rs4_non_import_error_from_claude_agent_sdk_propagates(monkeypatch):
    from self_learn import invocation

    for name in list(sys.modules):
        if name == _INVOCATION_SDK_PREFIX or name.startswith(_INVOCATION_SDK_PREFIX + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    class _BoomLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None  # defer to the default module creation

        def exec_module(self, module):
            raise RuntimeError("boom-not-an-import-error")

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "claude_agent_sdk":
                return importlib.machinery.ModuleSpec(fullname, _BoomLoader())
            return None

    finder = _Finder()
    monkeypatch.delitem(sys.modules, "claude_agent_sdk", raising=False)
    sys.meta_path.insert(0, finder)
    # U-flip pins SELF_LEARN_BACKEND_WORKER=cli at rung 1 (conftest's
    # suite-wide default); clear it too, or it shadows this rung-2
    # override.
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    try:
        with pytest.raises(RuntimeError, match="boom-not-an-import-error"):
            invocation.backend_for("worker", home="/tmp")
    finally:
        sys.meta_path.remove(finder)


def test_rs6_lazy_import_target_resolves_by_identity(tmp_path, monkeypatch):
    from self_learn import invocation
    import self_learn.invocation_sdk as real_pkg

    # U-flip pins SELF_LEARN_BACKEND_WORKER=cli at rung 1 (conftest's
    # suite-wide default); clear it too, or it shadows this rung-2
    # override.
    monkeypatch.delenv("SELF_LEARN_BACKEND_WORKER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    backend = invocation.backend_for("worker", home=tmp_path)
    assert type(backend) is real_pkg.SdkBackend


def test_rs7_project_dependencies_include_sdk_and_extra_is_empty_alias():
    """`DEP1`/`DEP2`/`DEP3` -- INVERTED (§6): `claude-agent-sdk` moved
    from the `[sdk]` extra into `dependencies` -- a machine can no longer
    stay on `backend=cli` (that condition is what `S-43` rested on, and
    U-cleanup is the unit that retires it). The `[sdk]` extra survives as
    an EMPTY alias (ruled, `Q-3`) so `pip install 'self-learn-cli[sdk]'`
    keeps resolving."""
    cli_pyproject = Path(worker.__file__).resolve().parents[2] / "pyproject.toml"
    text = cli_pyproject.read_text(encoding="utf-8")
    dep_block = text.split("[project.optional-dependencies]")[0]
    deps_section = dep_block.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "claude-agent-sdk" in deps_section

    extra_block = text.split("[project.optional-dependencies]", 1)[1]
    extra_section = extra_block.split("sdk = [", 1)[1].split("]", 1)[0]
    assert "claude-agent-sdk" not in extra_section


def test_rs8_lockfiles_no_package_added_or_removed_no_version_changed():
    """`RS8`'s actual content bound, per `BLOCKER-2`/`M61`: the set of
    `[[package]]` `(name, version)` pairs at HEAD must be IDENTICAL to
    `c2669a9` (the base commit) -- no package added, none removed, no
    version changed -- and the only stanza allowed to differ AT ALL is
    `self-learn-cli`'s own `dev-dependencies`/`metadata.requires-dev`
    blocks. Comparing only "is `claude-agent-sdk` present somewhere" (the
    old body) is satisfiable by a build that also silently bumped an
    unrelated locked version; a `git show c2669a9:<path>` comparison is
    what actually rules that out."""
    import tomllib

    repo_root = Path(worker.__file__).resolve().parents[5]
    cli_lock = Path(worker.__file__).resolve().parents[2] / "uv.lock"
    ui_lock = Path(worker.__file__).resolve().parents[3] / "ui" / "uv.lock"

    def _pkg_set(data: dict) -> set[tuple[str, str]]:
        return {(p["name"], p["version"]) for p in data["package"]}

    def _at_base(rel_path: str) -> dict:
        text = subprocess.run(
            ["git", "show", f"c2669a9:{rel_path}"],
            capture_output=True, text=True, cwd=str(repo_root), check=True,
        ).stdout
        return tomllib.loads(text)

    for lock_path, rel_path in (
        (cli_lock, "plugins/self-learn/cli/uv.lock"),
        (ui_lock, "plugins/self-learn/ui/uv.lock"),
    ):
        head_data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        base_data = _at_base(rel_path)

        names = [p["name"] for p in head_data["package"]]
        assert len(names) == len(set(names))  # sanity: no dup stanzas

        # The bound itself: identical (name, version) sets vs c2669a9.
        assert _pkg_set(head_data) == _pkg_set(base_data), (
            f"{rel_path}: package (name, version) set differs from c2669a9"
        )

        # Only `self-learn-cli`'s own stanza may differ AT ALL; every
        # other package's full stanza must be byte-for-byte the same dict.
        head_others = [p for p in head_data["package"] if p["name"] != "self-learn-cli"]
        base_others = [p for p in base_data["package"] if p["name"] != "self-learn-cli"]
        assert head_others == base_others, f"{rel_path}: a non-self-learn-cli stanza changed"

        cli_member = next(p for p in head_data["package"] if p["name"] == "self-learn-cli")
        if lock_path == cli_lock:
            dev = cli_member.get("dev-dependencies", {}).get("dev", [])
            assert any(d.get("name") == "claude-agent-sdk" for d in dev)
        requires_dev = cli_member.get("metadata", {}).get("requires-dev", {}).get("dev", [])
        assert any(d.get("name") == "claude-agent-sdk" for d in requires_dev)


# ===================================================================== #
# HG -- hygiene
# ===================================================================== #


def test_hg1_no_bare_claude_list_literal_outside_the_worker_invoke_claude_pattern():
    src = Path(__file__).read_text(encoding="utf-8")
    pattern = re.compile(r'\[\s*"claude"\s*\]')
    for lineno, line in enumerate(src.splitlines(), start=1):
        if pattern.search(line) and "worker._invoke_claude(" not in line:
            raise AssertionError(f"line {lineno}: {line}")


_HG2_SELF = "test_hg2_every_session_construction_sets_the_fake_cli_path"


def test_hg2_every_session_construction_sets_the_fake_cli_path():
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(__file__))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            if node.name == _HG2_SELF:
                continue  # this function's own body-source literals self-match the scan
            body_src = ast.get_source_segment(src, node) or ""
            constructs_session = "SdkBackend(" in body_src or "ClaudeAgentOptions(" in body_src
            if not constructs_session:
                continue
            params = {a.arg for a in node.args.args}
            deps_on_fixture = "sdk_cli_path" in params
            # a handful of tests deliberately probe options_kwargs() in
            # isolation (never constructing a session) or explicitly test
            # the not-found path with a bogus path -- both are fine
            # without the fixture as long as they never let a session
            # actually run against a real resolvable CLI.
            if "options_kwargs(" in body_src and "_run(" not in body_src and "_run_text(" not in body_src:
                continue
            assert deps_on_fixture, node.name

    # `BLOCKER-1` hardening: `monkeypatch.undo()` on the shared,
    # fixture-owned `monkeypatch` instance also reverts `sdk_cli_path`'s
    # `SELF_LEARN_SDK_CLI_PATH` (and any other env this file's fixtures
    # set) for the REST of the test -- exactly the mechanism that let a
    # real, credentialed session start. Any state that needs to unwind
    # mid-test uses a nested `pytest.MonkeyPatch()` context instead. An
    # AST `ast.Call` scan (not a whole-file substring search, which would
    # self-match THIS function's own error-message string literal) over
    # every OTHER function's own subtree.
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        if node.name == _HG2_SELF:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "undo"
                and isinstance(func.value, ast.Name)
                and func.value.id == "monkeypatch"
            ):
                raise AssertionError(
                    f"{node.name}: monkeypatch.undo() on the shared fixture instance is "
                    "forbidden in this file -- use `with pytest.MonkeyPatch.context() as mp:` "
                    "for state that needs to unwind mid-test (BLOCKER-1)"
                )


def test_hg3_the_fake_cli_never_touches_the_network():
    src = FAKE_CLI.read_text(encoding="utf-8")
    for token in ("subprocess", "socket", "urllib", "http"):
        assert token not in src, token


def test_hg4_cache_dir_writes_land_under_tmp_path(tmp_path, monkeypatch, sdk_cli_path):
    home = tmp_path / "hg4-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _run(_spec("worker", home=home, prompt="ok_text"))
    cache = worker.cache_dir()
    assert str(cache).startswith(str(tmp_path))
