"""U-sdkw (docs/specs/self-learn/drafts/u-sdkw-worker-contract-spec.md,
r5, CLEARED FOR BUILD) -- the worker's contract, on BOTH backends,
without flipping the worker to ``sdk``. 46 criteria, 11 groups
(``SU``/``PB``/``WS``/``RP``/``TO``/``FL``/``HA``/``BG``/``EV``/``FR``/
``HY``).

This unit ships no product code. This module + one sanctioned additive
scenario in ``fixtures/fake_claude.py`` (``Fake-3``, ruling ``V-2``) are
the entire deliverable (``MT-a``).

Tiers (``M-b``): T1 (in-process, ``install_fake``/``FakeStep``) drives
``run()``'s wiring; T2 (the bash ``claude`` shim) is the ``cli`` leg's
transport; T3 (the fake CLI via ``SELF_LEARN_SDK_CLI_PATH``) is the
``sdk`` leg's transport. No ``autouse`` fixture is defined here (``U-sdk``
``Sim-1a`` -- importing this module runs it in the SAME session as every
other shipped test)."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import inspect
import io
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from claude_agent_sdk import (
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
)

from self_learn import invocation, worker
from self_learn.invocation import Writes
from self_learn.invocation.contract import Outcome, SessionSpec
from self_learn.invocation_sdk import SdkOutcome
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod

from backends import install_fake
from test_worker import (  # noqa: F401 -- fixtures resolved by name
    Env,
    PROPOSAL_YAML_TEMPLATE,
    sdk_fake_worker,
    env,
    seed_pending,
    shim_writes,
)
from test_repair import _defect_script, _t4_missing_target, _t4_target_fixed
from test_invocation_sdk import FAKE_CLI, sdk_absent, sdk_cli_path  # noqa: F401

# Re-anchored twice at merge trains (2026-08-19), each time after verifying
# every inter-base drift was a sibling unit's gated landing:
#   89f8ef7 -> fd694de (U-docs/U-sdkr beneath this unit: shims.py +43/0
#   additive, test_invocation.py CN2 strict_mcp False->True), then
#   fd694de -> c3b48e7 (U-sdka's flip landing: the conftest analyst pin
#   9/0, test_invocation/test_invocation_sdk EDITED-8 functions,
#   fake_claude's analyst scenarios). From c3b48e7 the armor guards
# FUTURE edits; the historically-sanctioned deltas are verified in the
# gate records (misc/gates/) and commits 29f5d67 / a0d94a1.
BASE_COMMIT = "c3b48e7"

# ===================================================================== #
# Shared plumbing -- the Par-1 backend fixture, the M-c1 capture spy, and
# small local helpers. None of these re-implement anything the imported
# factories already provide (M-a); they are the trivial glue a param
# fixture body needs (P-a) plus proposal-body serialization the import
# table has no helper for.
# ===================================================================== #


#: STEP 0 (code-gate fold, safety-first, gate-reported): the gate's own
#: sweep of this module produced REAL claude sessions -- confirmed
#: independently (real model=claude-sonnet-5 usage in
#: ~/.claude/projects/.../pb2-home/*.jsonl, spawned from
#: ``test_pb2_driven_outcome_backend_asymmetry``). SHADOW-NOT-SUBTRACT:
#: a decoy ``claude`` -- exits 1 instantly, touches no network, counts
#: invocations -- prepended to PATH BENEATH every real/fake shim this
#: module builds afterward (later prepends win) and ABOVE the inherited
#: PATH's real binary, so that if a shim ever fails to be what PATH
#: resolves (however that happens), resolution lands on this harmless
#: decoy INSTEAD OF ``~/.local/bin/claude``. This is a belt-and-suspenders
#: backstop, not a substitute for a correct primary mechanism -- it does
#: not explain the leak, it makes the leak's blast radius zero regardless
#: of cause.
_DECOY_SCRIPT_TEMPLATE = '#!/bin/sh\necho -n . >> "{counter}"\nexit 1\n'


def _install_decoy_shadow(base_dir: Path, monkeypatch) -> Path:
    """Idempotent per ``base_dir``: writes the decoy once, then prepends
    its directory to PATH every call (harmless if repeated -- callers
    that build a real shim afterward always end up ahead of it, since
    each subsequent `monkeypatch.setenv("PATH", ...)` prepend wins)."""
    decoy_dir = base_dir / "decoy-claude-bin"
    decoy_dir.mkdir(exist_ok=True)
    counter = base_dir / "decoy-claude-counter"
    if not counter.exists():
        counter.write_text("", encoding="utf-8")
    decoy = decoy_dir / "claude"
    if not decoy.exists():
        decoy.write_text(_DECOY_SCRIPT_TEMPLATE.format(counter=counter), encoding="utf-8")
        decoy.chmod(0o755)
    monkeypatch.setenv("PATH", f"{decoy_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return counter


def _decoy_hits(counter: Path) -> int:
    if not counter.exists():
        return 0
    return len(counter.read_text(encoding="utf-8"))


class _Watchdog:
    """BLOCKER-2 (code-gate fold): a REAL watchdog for the TO group.
    `signal.alarm`/`SIGALRM` delivers into the blocking call itself,
    interrupting the syscall the event loop is parked in -- unlike a
    post-return `elapsed <= bound` assertion, which can only ever measure
    a call that ALREADY returned, and is therefore unreachable when the
    call never returns at all (`M31`: the sdk leg's `asyncio.wait_for`
    hardcoded to 1800s -- measured to hang the runner rather than redden,
    confirmed against this exact post-return form). Raises `TimeoutError`
    from inside the guarded block at `seconds`, which pytest reports as a
    failure (a redden) instead of a multi-minute hang."""

    def __init__(self, seconds: float):
        self.seconds = seconds

    def __enter__(self):
        def _handler(signum, frame):
            raise TimeoutError(
                f"TO-group watchdog fired after {self.seconds}s -- the call did not return in time"
            )

        self._old = signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def __exit__(self, exc_type, exc, tb):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._old)
        return False


@pytest.fixture(autouse=True)
def _step0_real_claude_shadow(tmp_path, monkeypatch):
    """Deliberate, documented exception to the module docstring's
    Sim-1a no-autouse-fixture rule: this is a SAFETY fixture, not a
    test-behavior fixture -- exactly the distinction that already
    justifies conftest.py's own session-scoped SDK spawn tripwire. Sim-1a
    guards against autouse fixtures quietly changing what a criterion
    observes; this fixture changes nothing any criterion reads (it never
    touches SELF_LEARN_* state, never builds a scenario), it only makes
    ``claude`` un-resolvable outside `tmp_path` for every test, cli or
    sdk, module-wide -- extending HY5 leg 1's property from "one test
    checks this of its own shim" to "true everywhere in this module,
    checked at every test's end." Runs before any explicitly-requested
    same-scope fixture (`backend`, `sdk_fake_worker`, ...) so its
    prepend is always the FLOOR, never the winner, when a real shim
    follows."""
    counter = _install_decoy_shadow(tmp_path, monkeypatch)
    yield counter
    resolved = shutil.which("claude")
    if resolved is not None:
        resolved_path = Path(resolved).resolve()
        assert str(resolved_path).startswith(str(tmp_path.resolve())), (
            "STEP 0 module-wide guard (HY5 leg 1, extended): `claude` "
            f"resolved OUTSIDE tmp_path at test end -- {resolved_path}"
        )


# U-cleanup-B DELETE (§8.3): `_build_cli_shim` called `shims.write_
# worker_claude_shim` directly to drive the `cli`-param leg's bash
# transport. `backend` (below) is COLLAPSED to `sdk`-only (`Par-1`,
# U-cleanup-A) and its own docstring already said so: "The `cli` branch
# and `_build_cli_shim` are UNUSED by this fixture from here on -- they
# stay defined (U-cleanup-B deletes them, §8.3)." `_apply_failure_env`'s
# `if param == "cli":` branch (the function's only remaining caller) is
# deleted alongside it, below.


def _build_sdk_env(monkeypatch) -> None:
    """`Par-1`'s sdk row (`B-5`/`HY3`): the ONLY sanctioned setter of
    `SELF_LEARN_SDK_CLI_PATH` inside this module besides the `backend`
    fixture itself -- `HY2` scans for this."""
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")


@dataclass
class _Backend:
    param: str
    fake_cli: Path | None  # sdk only

    # U-cleanup-B DELETE (§8.3): `prompt_of` -- "the one shape both legs
    # can answer" -- read `self.shim["call_prompt"](n)` on the `cli` leg
    # and returned `None` unconditionally on `sdk` (the ONLY leg left,
    # zero callers anywhere in this module even before this deletion:
    # `BG3`'s own two-witness mechanism replaced it). The `shim` field it
    # was the sole reader of is dropped alongside it.


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    """`Par-1`, COLLAPSED (U-cleanup-A `CV2`/`CB-3`): formerly
    `params=["cli", "sdk"]` -- every `(T2 + T3)` criterion parametrized
    over this fixture now runs the `sdk` leg ONLY and with NO
    parametrization suffix on its node id (`CB-3`: "the 43 `[sdk]` T2 legs
    survive... as unparametrized tests"). The `cli` branch and
    `_build_cli_shim` are UNUSED by this fixture from here on -- they stay
    defined (U-cleanup-B deletes them, §8.3) so any straggler direct
    caller is a clear NameError rather than a silent behavior change.
    STEP 0 / MAJOR-4 backstop: re-assert the decoy shadow explicitly here
    (the autouse fixture already installed it, this call is idempotent)
    -- the gate's finding was exactly "sdk falls to CliBackend with
    inherited PATH"; this is the row that makes that fall-through land on
    the decoy, never the real binary."""
    _install_decoy_shadow(tmp_path, monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    _build_sdk_env(monkeypatch)
    assert os.environ.get("SELF_LEARN_SDK_CLI_PATH") == str(FAKE_CLI)  # `PB3`
    return _Backend(param="sdk", fake_cli=FAKE_CLI)


# U-cleanup-A: `MAJOR-3`'s `_BACKEND_FIXTURE = backend` module-level alias
# (captured so `test_pb1_...` could read the fixture's declared `params`
# off its pytest marker) is removed -- the `backend` fixture no longer
# carries a `params` marker at all post-collapse (see its own
# docstring), so nothing needs the function object anymore; `test_pb1_...`
# now checks `backend.param` directly instead.


@dataclass
class _Captured:
    spec: SessionSpec
    kwargs: dict
    outcome: Outcome


def _spy_write_session(monkeypatch) -> list[_Captured]:
    """`M-c1` (THE capture mechanism) -- patches the PACKAGE-LEVEL
    `self_learn.invocation.write_session` binding, because that is the
    binding `worker._invoke_claude` calls (`spec = invocation.SessionSpec
    (...)` ... `invocation.write_session(spec)`). Patching
    `invocation.registry.write_session` instead (the `BK-a` mirror trap)
    is a SILENT NO-OP: `worker.py` never reads that binding.

    U-cleanup-B rebase (§8.1, CL9): there is no more argv to recompute
    (`spec.cli_argv_builder` is deleted). Records `(spec, options_kwargs
    (spec), outcome)` instead -- the sdk seam's own rendering of the
    spec, which is what every surviving caller actually needs to assert
    shape against, plus the outcome (the `CH10`-precedent shape) for
    criteria that need the driven verdict. `options_kwargs` can itself
    raise `CharterPatternUnsupported` for a deliberately-malformed
    `write_globs` pattern (`FL1`'s os-error/sdk cell uses exactly this
    to synthesize a failure) -- the REAL call site catches that
    internally (`backend.py:411`) and folds it into the returned
    `Outcome`; this spy must not pre-empt that by raising it a second
    time, uncaught, before `real()` ever runs."""
    captured: list[_Captured] = []
    real = invocation.write_session

    def spy(spec, **kwargs):
        try:
            rendered = backend_mod.options_kwargs(spec)
        except Exception:  # noqa: BLE001 -- real() below is the actual authority
            rendered = {}
        outcome = real(spec, **kwargs)
        captured.append(_Captured(spec=spec, kwargs=rendered, outcome=outcome))
        return outcome

    monkeypatch.setattr(invocation, "write_session", spy)
    return captured


class _Ctx:
    pass


def _call_cb(cb, tool_name, tool_input):
    import asyncio

    return asyncio.run(cb(tool_name, tool_input, _Ctx()))


def _worker_containment(home: Path, *, stage_on: bool = False, enforce: bool = True) -> invocation.Containment:
    return invocation.containment_for(
        "worker",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        home=str(home),
        stage_dir=home / "stage",
        stage_on=stage_on,
        enforce=enforce,
    )


def _spec_for(
    surface: str,
    *,
    home: Path,
    prompt: str,
    timeout: float = 20.0,
    containment: invocation.Containment | None = None,
    label: str = "",
    doctrine: str | None = None,
) -> SessionSpec:
    """U-cleanup-B rebase (§8.1, CL9): `worker.build_argv` and
    `SessionSpec.cli_argv_builder`/`.cli_settings_writer` are deleted --
    this helper's only caller (`test_pb2_driven_outcome_backend_
    asymmetry`) never passed `argv=` (the default path), so the whole
    settings-file/argv-recompute block is dead weight now, not a
    property anything still asserts. Replaced with the real seam's own
    `doctrine` field."""
    if containment is None:
        containment = _worker_containment(home)
    return SessionSpec(
        surface=surface,
        prompt=prompt,
        cwd=home,
        timeout=timeout,
        containment=containment,
        log=lambda _msg: None,
        label=label,
        doctrine=doctrine,
    )


def _dump_yaml(data: dict) -> str:
    """Serializes a proposal dict to YAML text the way a producer would
    emit it -- mirrors `test_repair.py`'s private `_dump` (not in
    `Mod-1`'s import table, so re-derived as the trivial serialization
    call it is; this is not a second proposal FACTORY -- the factories
    (`_t4_missing_target`/`_t4_target_fixed`) stay imported and reused)."""
    y = YAML(typ="safe")
    y.default_flow_style = False
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def _valid_proposal_yaml(env) -> str:
    """Mirrors `test_worker.py`'s private `_proposal_yaml` (only
    `PROPOSAL_YAML_TEMPLATE` itself is in `Mod-1`'s import table)."""
    return PROPOSAL_YAML_TEMPLATE.format(roster_sha=worker.skill_roster(env.home).sha)


def _installed_matches_written(written_text: str, installed_text: str) -> bool:
    """`WS6`'s "installed bytes equal written bytes" reads TRUE at the
    content level, not the byte level: `worker._install_staged` always
    follows the atomic copy with the CLI's own `stamp_proposal`
    (`ledger_ops.py`), which round-trip-loads the file and OVERWRITES
    `record_sha` unconditionally (08 §7.1 -- the model's own value, if
    any, is never trusted) -- shipped, documented, unrelated to either
    backend. So the comparison is: every OTHER key/value the model wrote
    survives verbatim, and `record_sha` is present on the installed side
    (the CLI's stamp) but absent on the written side (a model never
    emits one, `PROPOSAL_YAML_TEMPLATE`'s own docstring)."""
    y = YAML(typ="safe")
    written = y.load(written_text) or {}
    installed = y.load(installed_text) or {}
    assert "record_sha" not in written
    assert "record_sha" in installed
    installed_sans_sha = {k: v for k, v in installed.items() if k != "record_sha"}
    return written == installed_sans_sha


def _worker_events_files() -> list[Path]:
    return list(worker.cache_dir().glob("worker.tool-events.*.jsonl"))


def _latest_worker_events() -> list[dict]:
    files = _worker_events_files()
    assert files, "no worker.tool-events.*.jsonl file found"
    latest = max(files, key=lambda p: p.stat().st_mtime)
    return [json.loads(line) for line in latest.read_text(encoding="utf-8").splitlines() if line.strip()]


def _module_source_excluding(*func_names: str) -> str:
    """This module's own source, with the named top-level functions'
    BODIES blanked out -- a source-scan test's own assertion literals
    would otherwise self-match the very substrings it scans for, exactly
    the trap `test_invocation_sdk.py`'s `_HG2_SELF` skip exists to
    avoid."""
    src = Path(__file__).read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    blanked: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in func_names:
            start = node.lineno
            end = node.end_lineno or node.lineno
            blanked.update(range(start, end + 1))
    return "".join("\n" if (i + 1) in blanked else line for i, line in enumerate(lines))


def _repo_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(10):
        if (p / ".git").exists():
            return p
        p = p.parent
    raise RuntimeError("repo root not found above test_worker_contract.py")


def _git_show_base(relpath: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:{relpath}"],
        cwd=_repo_root(), capture_output=True, check=True,
    )
    return proc.stdout


_RID_COUNTER = [0]


def _next_rid() -> str:
    """A fresh, valid `lrn-[0-9a-f]{8}` id (`records.RECORD_ID_RE`) --
    hand-picked mnemonic hex strings are error-prone (a stray non-hex
    letter fails `Record.validate`), so every seeded record in this
    module gets one from here instead."""
    _RID_COUNTER[0] += 1
    return f"lrn-{_RID_COUNTER[0]:08x}"


# U-cleanup-B DELETE (§8.3): `_make_selective_claude_run` built a
# `subprocess.run` wrapper that raised for a `claude`-argv call only
# -- its sole callers were the `_apply_failure_env` `cli`-param
# `not-found`/`os-error` cells, deleted alongside it (below). Every
# caller passes `param="sdk"` now (§8.1).


def _apply_failure_env(kind: str, param: str, *, scratch: Path, monkeypatch) -> float:
    """`F-c`'s table, one cell. `scratch` is a directory OUTSIDE any
    ledger home this leg might also use (PATH-shim/empty-dir litter must
    never land inside a git-tracked worker home). Returns the timeout the
    caller should use for a direct `_invoke_claude` drive; for the
    ``timeout`` kind it ALSO sets `SELF_LEARN_INVOKE_TIMEOUT_SECS` so a
    `worker.run()`-driven caller (`FL3`) is bounded identically."""
    timeout = 20.0
    if kind == "unavailable":
        # `F-c`: identical on both legs by construction -- the registry
        # refuses BEFORE any backend is built. Poisons `claude_agent_sdk`
        # exactly as `test_invocation_sdk.py`'s `sdk_absent` fixture does
        # (never in the module import table since it is a FIXTURE, not a
        # plain function this body could call): `registry._resolve`'s
        # lazy `from ..invocation_sdk import SdkBackend` then raises
        # `ImportError`, caught as `BackendUnavailable`. Skipping this
        # step would leave `SELF_LEARN_SDK_CLI_PATH` unset and let a REAL
        # `SdkBackend` reach `_find_cli()` -- the exact hazard the
        # session-scoped tripwire exists to catch (caught it live while
        # building this leg).
        _install_decoy_shadow(scratch, monkeypatch)  # STEP 0 backstop
        for name in list(sys.modules):
            if name == "self_learn.invocation_sdk" or name.startswith("self_learn.invocation_sdk."):
                monkeypatch.delitem(sys.modules, name, raising=False)
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
        monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
        return timeout

    # U-cleanup-B DELETE (§8.3): the `if param == "cli":` branch (bash
    # shim / `_build_cli_shim`, selective-`subprocess.run` patches over
    # a real `["claude", ...]` argv) is gone -- every caller passes
    # `param="sdk"` now (`backend.param` is a `KNOWN_BACKENDS = ("sdk",)`
    # constant, §8.1), so it was unreachable dead code.

    # sdk
    _install_decoy_shadow(scratch, monkeypatch)  # STEP 0 / MAJOR-4 backstop
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    if kind == "not-found":
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", "/nonexistent/claude-fake")
        monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
        return timeout
    _build_sdk_env(monkeypatch)
    if kind == "exit":
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "error_result")
    elif kind == "timeout":
        timeout = 1.5
        monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "1.5")
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")
    # "os-error" on sdk: the caller mutates the containment (write_globs
    # with an unsupported "[" metacharacter) -- there is no env knob.
    return timeout


# ===================================================================== #
# SU -- the suite (SU1, SU2, SU3, SU5 are instrument-only; no function)
# ===================================================================== #

#: U-cleanup-B re-pins conftest.py/test_invocation.py/test_invocation_
#: sdk.py a further time on top of U-cleanup-A's content below (AG1's
#: tripwire deletion + retirement comment; the whole-file rebase §8.1
#: forces onto the seam's test suite). All three are already members of
#: `_SU4B_DIFF_EXEMPT` -- only the hash moves, not exempt-set membership.
#: U-servehermetic (2026-08-27) re-pins `conftest.py` again: `_worker_
#: test_defaults` now sets `XDG_CONFIG_HOME` to a fresh `tmp_path`
#: subdir, next to the pre-existing `XDG_CACHE_HOME` line, so
#: `serve.unit_dir()`'s new `XDG_CONFIG_HOME` fallback leg reads the
#: fixture dir instead of the real `~/.config/systemd/user` (the defect
#: this unit fixes -- a live host unit made 18 tests host-dependent).
#: Already a member of `_SU4B_DIFF_EXEMPT` from U-flip -- only the hash
#: moves, not exempt-set membership.
#: U-cachelit (2026-08-28) re-pins `conftest.py` a further time: a new
#: `_litter_namespace_guard` section is APPENDED whole (pure addition,
#: nothing existing edited) -- the session-scoped forward guard against
#: the measured 31,291-namespace cache-litter defect (root cause: the
#: UI package's module-scoped real-server test fixtures, fixed in
#: `plugins/self-learn/ui/tests/conftest.py`; this file's own addition
#: is the CLI-side backstop). Already a member of `_SU4B_DIFF_EXEMPT` --
#: only the hash moves, not exempt-set membership.
#: U-cachelit RE-ANCHOR (code gate r1, same day) re-pins `conftest.py`
#: yet again: the guard section was deleted and rewritten, not edited,
#: to fold M-1/M-2/M-3 -- a session-scoped `_env_floor_session` for the
#: CLI package, digest-based namespace attribution
#: (`_normalized_digests`/`_SESSION_HOMES`) instead of raw `env=`-string
#: matching, and a `pytest_terminal_summary` warn channel for
#: unattributable (concurrent-sibling) namespaces. Only the hash moves;
#: still a pure append over the pre-U-cachelit baseline (see `test_
#: u_sdka.py::_AR1_SANCTIONED_PIN_LINES`'s own RE-ANCHOR paragraph for
#: the full accounting), still a member of `_SU4B_DIFF_EXEMPT`.
_ARMOR_SHAS = {
    "plugins/self-learn/cli/tests/conftest.py": "09d1cfc25026c74684d263332cdd912619bd94b76fafef12f495833f84bddfe4",  # U-cachelit RE-ANCHOR (gate r1): guard section rewritten
    "plugins/self-learn/cli/tests/backends.py": "a2ba2d74f117a230740d10e3c9fa67bd30f751ce80ec59667c9136557a906dde",
    # merge 2026-08-28 (u-hostmode x master): only master changed these
    # four keys since base (1e77ff4) -- ours were byte-unchanged there,
    # so master's pinned values win outright.
    "plugins/self-learn/cli/tests/test_invocation.py": "2b76f2bc4515891734c695993f2a7c203799c5ca35db89002a33a32fcaf86b2a",  # FW-117 (2026-08-28): HY3/CN6/CN7 witness-set trim + gate r1 fold (CN9 docstring truth), see the dated paragraph below
    "plugins/self-learn/cli/tests/test_invocation_sdk.py": "124c0e8b310ce8dbfeea89348d0ea5a8cf9c96c071642f7e16e89a7ffa1b4e35",  # U-kl4 gate r1 fold (2026-08-28): B-1/N-D1/N-D2/N-D3, see the dated paragraph below
    # merge 2026-08-28 (u-hostmode x master): BOTH sides changed this key
    # (ours: REWRITTEN/_DS1_EXPECTED re-pinned for test_route_cli.py's REC9
    # fallout; master's: U-ancestry + U-corrob DS1 extensions + FW-117
    # entries) -- neither side's stale value is used; re-derived by
    # sha256-hashing the ACTUAL merged tests/test_u_fake.py bytes after
    # both edits (and the DS1 re-derivation the merge itself required)
    # were combined.
    "plugins/self-learn/cli/tests/test_u_fake.py": "16497e769bd132e47e3be69e470af34b9b2e1ecf75261d9ced6d11081eb25e03",
    "plugins/self-learn/cli/tests/test_worker.py": "53287efe8e8f58b0fcda9741f68ca8a0b9b437ccc82a97b8b8cb89784d4bcd7a",  # U-ancestry, 2026-08-28: S-52 (SCAN1) supersedes u-marker §3 criterion A; the four canon_excerpt tests are rewritten to the whole-file contract and criterion B is re-homed as SCAN8
    "plugins/self-learn/cli/tests/test_repair.py": "266d2a7b89c741b2e801f8431a31ef43a7c316ae8e7926beb0c03b6293e497c5",  # FW-117 (2026-08-28): B9/D5 rebase, see the dated paragraph below
}

#: U-flip: three of the eight pins above (conftest.py, test_invocation.py,
#: test_invocation_sdk.py) carry this unit's sanctioned delta (the
#: worker/worker-repair/miner-reader backend flip and its test fallout)
#: on top of the U-sdka base -- they are no longer byte-identical to
#: `BASE_COMMIT` and are excluded from the diff-empty check below. Their
#: hashes above ARE re-pinned to this unit's shipped content, so the
#: hash check continues to guard them against any FURTHER, unrelated
#: drift. A post-merge reconciliation pass (the `c0a49a9` precedent --
#: "post-merge reconciliation of cross-unit armor and scoping controls")
#: is expected to bump `BASE_COMMIT` itself once this unit lands, at
#: which point these three rejoin the diff-empty set.
#:
#: U-cleanup-A (this build) re-pins `test_invocation.py` and
#: `test_invocation_sdk.py` AGAIN, on top of the U-flip content already
#: reflected above -- the CV2/CB-3 sdk-migration fallout in those two
#: files (43-leg parametrization collapse, RO-6 byte-pin, ou3 rewrite,
#: cn10/av1 deletion, av4/lg1-lg6/fk2 rebase). It also adds
#: `test_worker.py` and `test_repair.py` to BOTH the hash pins (re-pinned
#: to this build's content) and the exempt set below -- `claude_cli_shim_
#: worker`'s fixture was rebuilt onto the sdk-backed `fake_claude.py`
#: shim-script scenario (§3.4/§8.4b), and one CLI-argv-only test was
#: deleted from each per the same disposition as `_run_argv_pins`.
#: `test_invocation.py`'s pin is re-pinned a THIRD time by this same
#: build's own fold round (code gate r1, `8uvjHmdKaUd6PI3tSyB-F`,
#: MAJOR-1/NIT-6): `test_lg7`/`test_wr1`/`test_wr5`/`test_wr6` un-skipped
#: and rebased onto the new `_analyst_fail_sdk` helper (also added,
#: `import sys` too), and two other tests' skip reasons were reworded
#: (NIT-6, skip-to-B disposition) -- still the same file, still this
#: unit's own authorized delta, so only the hash below moves; the
#: exempt-set membership above needs no change.
#: A second full-suite run (same fold round) surfaced one more: MAJOR-1's
#: `wr6` rewrite dropped the shared `sdk_absent` fixture from its params
#: (see that file's own comment on the fix), which broke `test_invocation_
#: sdk.py::test_su6_...`'s structural nine-name check -- fixed there by
#: removing `wr6` from `_SIM_2_NINE` (documented in place, same file), not
#: by reverting the runtime fix. That edit moves `test_invocation_sdk.py`'s
#: own hash pin above a third time; it was already in the exempt set.
#: `conftest.py` is NOT yet in this build's own delta (AG3's pin removal
#: lands separately, in-tree, later in this same build) -- when it does,
#: `conftest.py`'s hash above needs re-pinning too; it is already in the
#: exempt set below from U-flip so no further `_SU4B_DIFF_EXEMPT` edit
#: will be needed at that point, only a new hash.
#: U-cleanup-A also adds `test_u_fake.py`: its own internal `DS1`/`DS2`
#: armor (function-level, not this whole-file mechanism) had two gaps
#: this build's first FULL-suite run surfaced -- `test_fx2_analyst_
#: fixture_shape` still expected the pre-existing `"prompt"` key to be
#: absent, and `test_worker.py`/`test_repair.py`'s CLI-argv-only test
#: deletions (already reflected in THIS file's own hash pins/exempt set,
#: above) were never taught to `REWRITTEN`/the new `DS1_REMOVED`, so
#: `test_ds1`'s live base-vs-head function count silently drifted by one
#: per file. Both are `test_u_fake.py`-internal corrections, not scope
#: creep -- hash re-pinned to this build's content, same as the other
#: four.
#: U-cleanup-B re-pins `test_u_fake.py` a further time: `_batch_
#: permissions`/`_capture_batch_permissions` were added to `test_attrib.
#: py` as the replacement for the deleted `worker.write_settings_file`
#: (§8.1), widening `REWRITTEN` (six `test_attrib.py` entries whose
#: bodies now call the new helpers) and `DS1_ADDED` (the two helpers
#: themselves) plus `_DS1_EXPECTED["test_attrib.py"]`'s count/sha pin
#: and the `DS2`/`DS1c` literal `expected` sets that mirror both lists
#: -- again a `test_u_fake.py`-internal correction, hash re-pinned to
#: this build's content; already a member of the exempt set below.
#: U-cleanup-B re-pins `test_invocation.py` a FOURTH time (§8.3): the
#: dead `_ANALYST_CLAUDE_SHIM` bash-script constant is deleted (the
#: `analyst_shim` fixture beneath it was already fully sdk-routed and
#: never read it) and `claude_shim` is renamed to `claude_cli_shim_
#: worker` throughout (8 sites, `test_repair.py`'s `R-1` compat-alias
#: deletion's one consumer) -- same file, still this unit's own
#: authorized delta; already a member of the exempt set below.
#: U-cleanup-B re-pins `test_invocation.py` a FIFTH time (§11.1,
#: T-DOCTRINE-REACHES-SDK/M-5): adds a `backend_mod` import and
#: `test_m5_doctrine_reaches_sdk_system_prompt_from_the_real_call_site`,
#: which drives the REAL `analyst.analyze` call site (via the existing
#: `analyst_capture` fixture) and asserts the real doctrine file's text
#: lands in `options_kwargs(spec)["system_prompt"]["append"]` -- same
#: file, still this unit's own authorized delta; already a member of the
#: exempt set below.
#: FOLD ROUND (code gate r1, MAJOR-1): CV7's own instrument
#: (`pytest --fixtures-per-test | grep -cE "^claude_(cli_)?shim"`) measured
#: 132 -- the two fixtures' NAMES lied in a tree with no CLI backend, even
#: though the property (SDK-backed via `fake_claude.py`) already held.
#: `claude_cli_shim_worker` -> `sdk_fake_worker`, `claude_cli_shim_analyst`
#: -> `sdk_fake_analyst`, renamed at every use site across ALL 10 files
#: that touched either name (grep-verified, word-boundary safe, zero
#: compound identifiers extended either name) -- CV7's command now prints
#: 0. Re-pins conftest.py/test_invocation.py/test_invocation_sdk.py/
#: test_u_fake.py/test_worker.py/test_repair.py (6 of the 7 pinned files;
#: backends.py untouched by the rename) to this round's content; all six
#: already members of the exempt set below.
#:
#: *2026-08-28* **U-kl4** re-pins `test_invocation_sdk.py` again: the
#: root-cause fix for `test_kl4_hang_sigterm_ignored_child_is_gone_
#: after_run_sync_returns`'s host-global false-red (`pgrep -f
#: fake_clau[d]e.py` matched ANY process on the machine, not just this
#: run's own child -- measured 2/2 parallel-suite runs red, solo green).
#: The test now identifies its child by PID, read off a new
#: `SdkOutcome.child_pid` field (`backend.py`) instead of a name
#: pattern, with a positive control (`test_kl4a_...`, monkeypatches
#: `teardown_mod.kill_child` to a no-op and confirms the check reddens)
#: plus two shared identity-check helpers (`_proc_start_ticks`/
#: `_child_gone`). The `NOTE-14` comment is rewritten in place to
#: describe the new check rather than deleted, since the file's other
#: `NOTE-*` comments are kept as historical markers the same way. A
#: first version of this fix threaded the pid through `spec.log()`
#: instead of a new `SdkOutcome` field -- MEASURED to break
#: `test_lg1`/`test_lg6`/`test_fk2` (`test_invocation.py`), `test_ou4`
#: (this file's sibling `test_invocation_sdk.py`), and `test_fl2`
#: (`test_worker_contract.py` itself, below) by adding an unexpected
#: line to every clean session's log; reverted before it shipped.
#: `backend.py` itself is untouched by any of this file's own pins
#: (not one of the 7) -- its `SdkOutcome.child_pid` addition has no
#: whole-file armor here to move.
#:
#: *2026-08-28* **U-kl4 gate r1 fold** re-pins `test_invocation_sdk.py`
#: a further time (1 BLOCKER / 0 MAJOR / 3 NOTE-or-DIRECT, folded, same
#: worktree, uncommitted). `B-1` (must-fix): `test_kl4a_...`'s `try/
#: finally` was scoped too narrowly -- `assert outcome.failure ==
#: "timeout"` and `assert pid is not None` ran OUTSIDE the `try`, so
#: either firing left `kill_child()` neutered and nothing to reap the
#: child (`K-5`'s sweep can't find it either, since `_drive`'s
#: `finally` already cleared the sidecar) -- a real ppid-1 orphan,
#: reproduced live during gate review and killed by hand from its pid.
#: Fixed: `pid = outcome.child_pid` is captured FIRST, every assertion
#: moved INSIDE the `try`, and the `finally` SIGKILLs + best-effort-
#: reaps (`_reap_best_effort`, new) the captured pid whenever it is not
#: `None`. `N/D-3`: the kill now re-checks `_proc_start_ticks(pid)`
#: immediately before sending `SIGKILL` (not just once at capture
#: time), guarding the ~1.5s window `_child_gone`'s own poll can take
#: -- kills only if the ticks still match. `N/D-2`: a new committed
#: test, `test_kl4b_child_pid_is_none_on_a_path_where_no_child_ever_
#: spawned`, asserts `child_pid is None` on the `not-found` leg (the
#: one the gate probed) -- one assertion, docstring cites `N/D-2`.
#: `N/D-1` (accepted as-is, no code change): one sentence added to the
#: `NOTE-14` comment block stating the PID-reuse guard's own failure
#: mode is a slower false RED, never a false green.
#: U-ancestry re-pins `test_u_fake.py` a further time (same build as the
#: `test_worker.py` re-pin above, 2026-08-28): the SCAN1/SCAN8 rewrite of
#: `test_worker.py`'s four `canon_excerpt` tests (S-52) surfaced the same
#: `test_ds1`-internal drift class U-cleanup-A/-B already fixed here
#: twice -- `DS1_REMOVED` gains the four superseded names, `DS1_ADDED`
#: gains the four replacement tests plus two new shared fixture helpers
#: (`_scan8_filler`/`_scan8_fixture_lines`), and `test_ds1b`/`test_ds1c`'s
#: mirrored `expected` sets and counts move with them. `_DS1_EXPECTED
#: ["test_worker.py"]`'s own (count, sha) pin also moves (59 -> 55): the
#: four newly-excluded base-side names drop out of that pin's base-only
#: census. Already a member of the exempt set below.
#:
#: *2026-08-28* **U-fw117** re-pins `test_invocation.py`, Gate r1 fold (same day): `test_invocation.py` re-pinned again for a docstring-only edit to `test_cn9_direction_guard_one_hop_local_taint` (it had named the deleted CN6/CN7 legs); hy5 row re-measured to (737, 760).
#: `test_repair.py`, and `test_u_fake.py` (FW-117, `14-forward-work-
#: map.md:172`):
#: `worker.write_repair_settings_file` is DELETED, not merely left
#: unread -- it wrote a real `worker.repair.settings.json` but nothing
#: under the sdk backend ever read it back (`options_kwargs()` passes
#: `settings=None` unconditionally, `A-2`; the cli-era `--settings
#: <path>` reader left with `CliBackend`). `test_invocation.py`:
#: `_HY3_SHAS`/`test_hy3_witness_b_is_sha_pinned` trimmed from three
#: witnesses to two; `SETTINGS_WITNESS`, `test_cn6_witnesses_a_and_b_
#: agree_statically`, and `test_cn7_repair_leg_over_both_enforce_values`
#: DELETED (no witness function left to agree against, same reasoning
#: as the already-deleted `test_cn8`/`test_cn7_worker_leg...` above).
#: `test_repair.py`: `test_b9_kill_switch_disables_composition` drops
#: its now-vacuous "settings file does NOT exist" leg (true either way
#: once the function is deleted, so no longer discriminates the kill
#: switch); `test_d5_the_narrowed_repair_scope_is_real` rebased onto a
#: `invocation.write_session` spy capturing the real `SessionSpec.
#: containment` instead of reading a file that no longer exists, plus a
#: new mutation-detecting `not ... .exists()` assertion (FW-117's whole
#: point). `test_worker_contract.py` itself (this file, the pinner, not
#: self-pinned) also gained `test_rp1a_repair_round_writes_no_settings_
#: artifact_under_cache_dir` (new) and rebased `test_rp1`/`test_ha1_
#: hatch_open_omits_default_mode` the same way -- all three verified RED
#: under a temporarily-reinstated one-line write at the repair call
#: site, reverted before shipping; see the build report. `test_u_fake.
#: py`'s `DS1`/`DS2` instrument (function-level armor, not this
#: whole-file mechanism) gained the matching `REWRITTEN`/`DS1_ADDED`
#: entries and re-derived `_DS1_EXPECTED` count/sha pins for both
#: touched modules, per its own house rules -- see that file's comments.
#: All three re-pinned files already members of `_SU4B_DIFF_EXEMPT`
#: below -- only the hash moves, not exempt-set membership.
_SU4B_DIFF_EXEMPT = {
    "plugins/self-learn/cli/tests/conftest.py",
    "plugins/self-learn/cli/tests/test_invocation.py",
    "plugins/self-learn/cli/tests/test_invocation_sdk.py",
    "plugins/self-learn/cli/tests/test_worker.py",
    "plugins/self-learn/cli/tests/test_repair.py",
    "plugins/self-learn/cli/tests/test_u_fake.py",
}

_FAKE_CLAUDE_RELPATH = "plugins/self-learn/cli/tests/fixtures/fake_claude.py"


def test_su4a_whole_file_armor_shas():
    """`SU4` clause (a) -- SEVEN whole-file pins, byte-identical to base
    (U-cleanup-B, §8.3: `shims.py`'s own pin is REMOVED, not exempted --
    the file it protected is deleted, and a pin over a nonexistent path
    can only ever crash `read_bytes()`, never usefully pass or fail).
    The LITERAL sha constants are extracted with `git show 89f8ef7:...`
    (never a working tree that may already carry an edit, `U-seam`
    `D-27`) -- that provenance is fixed once, in `_ARMOR_SHAS` itself.
    The TEST's own job is the other half: hash the file as it stands
    RIGHT NOW (`path.read_bytes()`) and require it still matches.

    The diff-empty half uses a SINGLE ref (`git diff 89f8ef7 -- <path>`,
    base commit vs the WORKING TREE), not `89f8ef7..HEAD` (base commit vs
    the HEAD commit): this unit's tree stays uncommitted through the
    build (`git diff --stat` shows real output), and this unit's own
    `HEAD` never moves off the base commit while that holds -- so the
    two-ref form is vacuously empty regardless of what the working tree
    actually carries, and would defeat the very obligation `D-27`
    exists for. U-flip/U-cleanup-A/U-cleanup-B: the diff-empty half is
    now scoped to the ONE file (`backends.py`) not exempted by
    `_SU4B_DIFF_EXEMPT` (see that constant) -- the hash pins above still
    cover all seven, unconditionally."""
    for relpath, expected in _ARMOR_SHAS.items():
        working_tree_path = _repo_root() / relpath
        actual = hashlib.sha256(working_tree_path.read_bytes()).hexdigest()
        assert actual == expected, (
            "Shipped armor changed. If this was deliberate, U-sdkw is the "
            f"wrong unit for it -- see §7.5. ({relpath})"
        )
    diff_checked = [p for p in _ARMOR_SHAS if p not in _SU4B_DIFF_EXEMPT]
    proc = subprocess.run(
        ["git", "diff", "--stat", BASE_COMMIT, "--", *diff_checked],
        cwd=_repo_root(), capture_output=True, text=True, check=True,
    )
    assert proc.stdout.strip() == "", proc.stdout


def _load_module_from_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fake_claude_module():
    path = Path(__file__).parent / "fixtures" / "fake_claude.py"
    return _load_module_from_path(path, "_fake_claude_under_test")


#: U-cleanup-A's sanctioned delta to `fake_claude.py`, layered on top of
#: `BASE_COMMIT`'s already-re-anchored content (analyst scenarios, prior
#: units' growth). Following the SAME "re-anchor" pattern legs 2-4's own
#: comments describe for earlier units (29f5d67, the U-sdka/U-flip
#: growth folded into `BASE_COMMIT` itself): rather than bumping
#: `BASE_COMMIT` again mid-build, this build's specific additions/edits
#: are named explicitly so leg 1's byte-identity check, leg 2's name-set
#: check, leg 3's key-set check, and leg 4's statement-sequence check
#: each stay strict against anything ELSE while tolerating exactly this.
#:
#: `main` and `_scenario_error_result` are EDITED (leg 1 exemption, not
#: additions) -- `main` gains per-call argv/prompt capture and
#: `_CURRENT_INVOCATION` bookkeeping; `_scenario_error_result` gains an
#: optional `FAKE_CLAUDE_ERROR_TEXT` override with the "boom" default
#: preserved (see the function's own comment, and `test_u_sdka.py`'s
#: `_HY3_SCENARIO_SHAS` re-pin of the same function). The five new
#: functions back the bash-shim-script interpreter that lets the
#: migrated `sdk_fake_worker`/`sdk_fake_analyst` fixtures
#: route the ~109 behaviour tests' existing `CLAUDE_SHIM_SCRIPT_<n>`
#: content through the sdk-backed fake instead of a real bash process.
#: `_peek_invocation` is a non-destructive counterpart to the pre-
#: existing `_next_invocation` (armored, unedited) -- added after `main`
#: was found double-incrementing `_scenario_ok_write_real`'s own on-disk
#: counter (see `_peek_invocation`'s own docstring).
_SU4B_SANCTIONED_EDITED_FUNCS = {"main", "_scenario_error_result"}
_SU4B_SANCTIONED_NEW_FUNCS = {
    "_capture_argv_per_call",
    "_capture_prompt_per_call",
    "_parse_shim_script",
    "_scenario_shim_script",
    "_peek_invocation",
}
_SU4B_SANCTIONED_NEW_SCENARIO_KEYS = {"shim_script"}
#: leg 4's sanctioned new top-level, non-`FunctionDef` statements, keyed
#: by `_stmt_key` so an insertion can be recognised and skipped without
#: caring WHERE it lands -- `import re` (regex-based shim-script
#: parsing), the `_CURRENT_INVOCATION` counter, the `_ShimScriptError`
#: exception class, and eight precompiled `re.Pattern` constants the
#: parser matches shim-script ops against (`_PRINT_HEREDOC_RE` added
#: after `test_composer.py::_shim_env`'s migration needed a no-target-
#: heredoc "print to the wire" op alongside the file-write ops;
#: `_ECHO_RE` added after `test_miner.py::test_artifact_contract_
#: sweeps_strays`'s migration needed a third single-line write idiom,
#: `echo CONTENT > path`, alongside heredoc and `printf`).
_SU4B_SANCTIONED_NEW_STMT_KEYS = {
    ("import", ("re",)),
    ("assign", "_CURRENT_INVOCATION"),
    ("class", "_ShimScriptError"),
    ("assign", "_HEREDOC_RE"),
    ("assign", "_PRINT_HEREDOC_RE"),
    ("assign", "_PRINTF_RE"),
    ("assign", "_ECHO_RE"),
    ("assign", "_RM_RE"),
    ("assign", "_TOUCH_RE"),
    ("assign", "_MV_RE"),
    ("assign", "_INERT_RESIDUE_RE"),
}


def _stmt_key(node: ast.AST) -> tuple:
    if isinstance(node, ast.Import):
        return ("import", tuple(sorted(a.name for a in node.names)))
    if isinstance(node, ast.ImportFrom):
        return ("importfrom", node.module, tuple(sorted(a.name for a in node.names)))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return ("assign", node.target.id)
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return ("assign", node.targets[0].id)
    if isinstance(node, ast.ClassDef):
        return ("class", node.name)
    return ("other", ast.dump(node))


def test_su4b_fake_claude_additive_only(tmp_path):
    """`SU4` clause (b) -- the ONE file `V-2` lets grow, pinned per
    function (`FK3-d`), four legs, all against `git show 89f8ef7:...`
    bytes. Both the base and the current function sources are extracted
    via `inspect.getsource` on an IMPORTED MODULE (leg 1's own runtime-
    binding requirement) -- the base copy is materialized to a real file
    first so `inspect.getsource` (which reads from `linecache`/disk, and
    includes the trailing newline `ast.get_source_segment` omits) sees
    the SAME extraction convention on both sides."""
    base_bytes = _git_show_base(_FAKE_CLAUDE_RELPATH)
    base_src = base_bytes.decode("utf-8")
    base_tree = ast.parse(base_src, filename="base_fake_claude.py")
    base_func_names = {n.name for n in base_tree.body if isinstance(n, ast.FunctionDef)}

    base_path = tmp_path / "base_fake_claude.py"
    base_path.write_text(base_src, encoding="utf-8")
    base_mod = _load_module_from_path(base_path, "_fake_claude_base")
    base_shas = {
        name: hashlib.sha256(inspect.getsource(getattr(base_mod, name)).encode("utf-8")).hexdigest()
        for name in base_func_names
    }

    cur_path = Path(__file__).parent / "fixtures" / "fake_claude.py"
    cur_src = cur_path.read_text(encoding="utf-8")
    cur_tree = ast.parse(cur_src, filename=str(cur_path))
    cur_func_names = {n.name for n in cur_tree.body if isinstance(n, ast.FunctionDef)}

    fake_claude_mod = _load_fake_claude_module()

    # leg 1: every base function's RUNTIME-BOUND source is byte-unchanged
    # -- resolved through the imported MODULE, never an ast-first-match
    # (the gate's shadowing-redefinition evasion hashed the ORIGINAL def
    # under a first-match reading and would have passed; the runtime
    # binding hashes the shadow and reddens -- keep this form). Names in
    # `_SU4B_SANCTIONED_EDITED_FUNCS` are exempted from byte-identity
    # (U-cleanup-A's own edits, see that constant's comment) but must
    # still exist and still be functions.
    for name in base_func_names:
        assert name in cur_func_names, f"{name} missing from the current file"
        if name in _SU4B_SANCTIONED_EDITED_FUNCS:
            continue
        fn = getattr(fake_claude_mod, name)
        live_src = inspect.getsource(fn)
        assert hashlib.sha256(live_src.encode("utf-8")).hexdigest() == base_shas[name], name

    # leg 2: no top-level names beyond base and this unit's sanctioned
    # four. (Originally asserted the delta was exactly this unit's
    # sanctioned pair {_scenario_ok_write_real, _next_invocation};
    # BASE_COMMIT now includes that growth plus U-sdka's analyst
    # scenarios, so from here any growth beyond `_SU4B_SANCTIONED_NEW_
    # FUNCS` is unsanctioned until a gated unit re-anchors. The original
    # verification lives at 29f5d67.)
    new_names = cur_func_names - base_func_names
    assert new_names == _SU4B_SANCTIONED_NEW_FUNCS, (new_names, _SU4B_SANCTIONED_NEW_FUNCS)

    # leg 3: SCENARIOS' key set gained nothing beyond base and this
    # unit's sanctioned "shim_script" (post-re-anchor form; originally
    # "exactly ok_write_real" -- see leg 2's note); every base key
    # survives bound to its ORIGINAL function (by __name__).
    base_scenarios = base_mod.SCENARIOS
    cur_scenarios = fake_claude_mod.SCENARIOS
    base_keys = set(base_scenarios.keys())
    cur_keys = set(cur_scenarios.keys())
    assert cur_keys - base_keys == _SU4B_SANCTIONED_NEW_SCENARIO_KEYS, (
        cur_keys - base_keys, _SU4B_SANCTIONED_NEW_SCENARIO_KEYS
    )
    assert base_keys <= cur_keys
    for key in base_keys:
        assert base_scenarios[key].__name__ == cur_scenarios[key].__name__, key

    # leg 4: the file's top-level non-FunctionDef statements are exactly
    # base's, in the SAME order, plus `_SU4B_SANCTIONED_NEW_STMT_KEYS`'s
    # entries inserted anywhere -- compared as a normalized ast.dump of
    # the statement list with the sanctioned insertions filtered out
    # first (catches the gate's own evasion: an appended module-level
    # rebinding of a pre-existing global, which passes legs 1-3 and the
    # additive numstat; also catches a REORDERED or EDITED pre-existing
    # statement, since the filtered sequence must still dump-match base
    # position for position).
    def _find_scenarios_assign(tree: ast.Module) -> ast.Assign:
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "SCENARIOS"
            ):
                return node
        raise AssertionError("SCENARIOS assignment not found")

    base_scen_node = _find_scenarios_assign(base_tree)
    cur_scen_node = _find_scenarios_assign(cur_tree)

    base_other = [
        n for n in base_tree.body if not isinstance(n, ast.FunctionDef) and n is not base_scen_node
    ]
    cur_other = [
        n for n in cur_tree.body if not isinstance(n, ast.FunctionDef) and n is not cur_scen_node
    ]

    cur_other_keys = [_stmt_key(n) for n in cur_other]
    sanctioned_idx = [i for i, k in enumerate(cur_other_keys) if k in _SU4B_SANCTIONED_NEW_STMT_KEYS]
    assert {cur_other_keys[i] for i in sanctioned_idx} == _SU4B_SANCTIONED_NEW_STMT_KEYS, (
        "sanctioned-new-statement set mismatch -- either an expected addition is "
        "missing, or an unsanctioned statement's shape collided with a sanctioned key",
        {cur_other_keys[i] for i in sanctioned_idx},
    )
    filtered_cur_other = [n for i, n in enumerate(cur_other) if i not in sanctioned_idx]
    assert len(base_other) == len(filtered_cur_other), (
        "top-level non-FunctionDef statement count changed beyond the sanctioned "
        "insertions -- an appended module-level statement (e.g. a rebound global) "
        "is not a sanctioned delta"
    )
    for b, c in zip(base_other, filtered_cur_other):
        assert ast.dump(b) == ast.dump(c)

    base_dict, cur_dict = base_scen_node.value, cur_scen_node.value
    assert isinstance(base_dict, ast.Dict) and isinstance(cur_dict, ast.Dict)
    base_pairs = {ast.dump(k): ast.dump(v) for k, v in zip(base_dict.keys, base_dict.values)}
    cur_pairs = {ast.dump(k): ast.dump(v) for k, v in zip(cur_dict.keys, cur_dict.values)}
    assert set(base_pairs) <= set(cur_pairs)
    for k, v in base_pairs.items():
        assert cur_pairs[k] == v, "a pre-existing SCENARIOS entry changed"
    # post-re-anchor: growth is exactly this unit's sanctioned "shim_script" key
    # (was == 1 pre-re-anchor, == 0 post-U-flip-re-anchor; see leg 2's note)
    assert len(set(cur_pairs) - set(base_pairs)) == len(_SU4B_SANCTIONED_NEW_SCENARIO_KEYS)


# ===================================================================== #
# PB -- the parametrized backend harness
# ===================================================================== #


def test_pb1_backend_identity_per_param(backend, tmp_path):
    from self_learn.invocation_sdk import SdkBackend as _IndependentSdkBackend

    # U-cleanup-A COLLAPSE + RE-BASELINE (§8.4b): MAJOR-3's original
    # first clause read the `backend` fixture's `params=("cli", "sdk")`
    # marker off `_fixture_function_marker` -- CV2/CB-3 collapsed the
    # fixture to unparametrized-sdk-only (see `backend`'s own
    # docstring), so there is no `params` marker left to read; a plain
    # `@pytest.fixture()` carries no `_fixture_function_marker` at all,
    # so the old clause would now raise `AttributeError`, not just fail
    # an assertion. Rebaselined to the surviving half of PB1's intent --
    # that the fixture yields exactly one identity, sdk, no other pole
    # reachable through it -- checked directly against `backend.param`
    # rather than against marker metadata that no longer exists.
    assert backend.param == "sdk"

    home = tmp_path / "pb1-home"
    home.mkdir()
    assert type(invocation.backend_for("worker", home=home)) is _IndependentSdkBackend
    assert type(invocation.backend_for("worker-repair", home=home)) is _IndependentSdkBackend


def test_pb2_driven_outcome_backend_asymmetry(backend, tmp_path, monkeypatch):
    home = tmp_path / "pb2-home"
    home.mkdir()
    spec = _spec_for("worker", home=home, prompt="ok_text")
    outcome = invocation.write_session(spec)
    if backend.param == "sdk":
        assert isinstance(outcome, SdkOutcome)
    else:
        assert not isinstance(outcome, SdkOutcome)


def test_pb3_sdk_param_always_uses_the_shipped_fake(backend):
    if backend.param != "sdk":
        pytest.skip("sdk-param-only criterion")
    assert os.environ.get("SELF_LEARN_SDK_CLI_PATH") == str(FAKE_CLI)


# `test_pb4_cli_param_shim_actually_reached` DELETED (code gate r1
# MAJOR-2 fold, 8uvjHmdKaUd6PI3tSyB-F): post-collapse the `backend`
# fixture always yields `param == "sdk"`, so `if backend.param != "cli":
# pytest.skip(...)` fired on 100% of invocations -- a permanently-
# skipped, zero-assertion node that still counted toward AG4. Deleted
# per §8.4's own explicit disposition for `pb4_cli_param_shim_actually_
# reached` (delete class).


# ===================================================================== #
# WS -- the write scope and the twin witness
# ===================================================================== #


def test_ws1_batch_containment_and_settings_agree(backend, env, monkeypatch):
    """U-cleanup-B RE-BASELINE: `worker.write_settings_file` (Witness B
    for the BATCH round) is deleted (§8.1) -- there is no on-disk
    settings file to re-parse and compare against Witness A anymore.
    Surviving half: the real call site's containment (Witness A) is
    what `write_session` actually captures, and the sdk seam renders it
    as `settings=None` (`CT2`/`OP4`'s own assertion, re-checked here
    against the REAL batch-round spec rather than a hand-built one)."""
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    captured = _spy_write_session(monkeypatch)
    worker.run(env.home)
    batch_specs = [c for c in captured if c.spec.surface == "worker"]
    assert batch_specs, "no batch invocation captured"
    cap = batch_specs[-1]
    assert cap.spec.containment.write_globs == (f"{worker.stage_dir()}/**",)
    assert cap.spec.containment.write_exact == ()
    assert cap.kwargs["settings"] is None


def test_ws2_sdk_charter_frontier_matches_scope1(env, sdk_cli_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")

    # Case A: a stage-scoped target is approved.
    rid_a = _next_rid()
    seed_pending(env, rid=rid_a)
    stage_target = worker.stage_dir() / f"{rid_a}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(stage_target))
    captured = _spy_write_session(monkeypatch)
    worker.run(env.home)
    outcome_a = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert isinstance(outcome_a, SdkOutcome)
    assert outcome_a.denials == ()
    events_a = _latest_worker_events()
    tool_results_a = [e for e in events_a if e.get("kind") == "tool_result"]
    assert tool_results_a and tool_results_a[-1]["content"] == "ok"

    # Case B: a ledger proposals/ path is denied.
    captured.clear()
    rid_b = _next_rid()
    seed_pending(env, rid=rid_b)
    ledger_target = env.bucket / "proposals" / f"{rid_b}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(ledger_target))
    worker.run(env.home)
    outcome_b = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert len(outcome_b.denials) == 1
    assert outcome_b.denials[0]["source"] == "charter"
    assert outcome_b.denials[0]["tool"] == "Write"
    resolved = str(ledger_target.resolve())
    assert outcome_b.denials[0]["reason"] == (
        f"self-learn invocation charter: Write write scope does not include {resolved}"
    )
    events_b = _latest_worker_events()
    denials_b = [e for e in events_b if e.get("type") == "denial"]
    assert len(denials_b) == 1
    tool_results_b = [e for e in events_b if e.get("kind") == "tool_result"]
    assert tool_results_b and tool_results_b[-1]["is_error"] is True


# U-cleanup-B DELETE ("CLI-only named tests" class, same shape as
# `test_fr1`/`test_hy5_cli`/`test_ws5a`): `test_ws3_cli_witness_b_is_
# stage_permission_rules` drove the `sdk_fake_worker` fixture
# (a real `CliBackend` transport) and re-parsed `worker.cache_dir() /
# "worker.settings.json"` -- the BATCH round's Witness B on-disk
# settings file. Both the fixture's transport and the file it wrote are
# gone: `worker.write_settings_file` is deleted (§8.1) and the batch
# round has passed `settings=None` to the sdk seam ever since (`WS1`'s
# own re-baseline above). There is no witness B left for this surface
# to compare against.


def test_ws4_stage_disabled_inverts_the_frontier(backend, env, monkeypatch):
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (re-parsed `worker.cache_dir() / "worker.settings.json"` -- doubly
    # dead, since `backend.param` can only be `"sdk"` now AND that file
    # is never written any more, `write_settings_file` deleted, §8.1) is
    # gone; only the sdk branch's body remains, unconditional.
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    rid_a = _next_rid()
    seed_pending(env, rid=rid_a)
    ledger_target = env.bucket / "proposals" / f"{rid_a}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(ledger_target))
    captured = _spy_write_session(monkeypatch)
    worker.run(env.home)
    outcome_a = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert outcome_a.denials == ()

    captured.clear()
    rid_b = _next_rid()
    seed_pending(env, rid=rid_b)
    stage_target = worker.stage_dir() / f"{rid_b}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(stage_target))
    worker.run(env.home)
    outcome_b = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert len(outcome_b.denials) == 1


# U-cleanup-B DELETE ("CLI-only named tests" class): `test_ws5a_stdout_
# never_parsed_cli_behavioral` drove the `sdk_fake_worker`
# fixture (a real `CliBackend` transport) for the batch round and
# `worker.build_argv` for the repair-surface direct drive -- both gone
# (§8.1). The property WS5 names (`Outcome.stdout` is always `""`,
# regardless of noise on the real stdout) survives on the sdk leg,
# `test_ws5b_stdout_never_parsed_sdk_behavioral` below.


def test_ws5b_stdout_never_parsed_sdk_behavioral(env, sdk_cli_path, monkeypatch):
    # MAJOR-2 (code-gate fold): WS5's spec text asserts `Outcome.stdout
    # == ""` on BOTH worker surfaces -- this was previously unimplemented
    # (only `RunResult.status` was checked, which says nothing about
    # what `Outcome.stdout` itself carries). Added via the `M-c1` spy.
    # U-cleanup-B RE-BASELINE (§8.4b, incidental reference): the repair
    # surface's direct drive no longer builds a settings file/argv pair
    # (`worker.build_argv` deleted, §8.1) -- `_invoke_claude`'s new
    # signature has no argv parameter at all.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_text")
    captured = _spy_write_session(monkeypatch)
    seed_pending(env, rid=_next_rid())
    result = worker.run(env.home)
    assert result.status == "failed"
    batch_outcome = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert batch_outcome.stdout == ""

    captured.clear()
    worker._invoke_claude(
        "prompt", 20.0, env.home,
        label="repair ", containment=invocation.DEGRADED_WORKER_CONTAINMENT,
    )
    repair_outcome = captured[-1].outcome
    assert repair_outcome.stdout == ""


def test_ws5c_stdout_never_parsed_t1(env, request, monkeypatch):
    from self_learn.invocation import Text

    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    fake = install_fake(request, monkeypatch, [Text("noise on stdout")])
    result = worker.run(env.home)
    assert result.status == "failed"
    assert fake.specs


def test_ws5d_structural_no_stdout_binding():
    """WS5's actual property: `Outcome.stdout` is always `""` on both
    worker surfaces, and worker.py never READS it, even when the
    model's real stdout carries noise. This used to be enforced by a
    blanket ban on ever BINDING `write_session`'s result at all -- a
    stricter proxy that held only because there was previously no
    legitimate reason to bind it. FW-107 (U-opsfix) gives worker.py
    one: `_invoke_claude` now binds the Outcome to thread its
    `.denials` (charter-sourced only) into the run summary's new log
    line -- `.stdout` is never touched. Narrowed to what WS5 actually
    asserts: no `.stdout` attribute access on any name bound from a
    `write_session`/`text_session` call, anywhere in the module."""
    src = Path(inspect.getfile(worker)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    bound_names: set[str] = set()
    for node in ast.walk(tree):
        value = None
        target_names: list[str] = []
        if isinstance(node, ast.Assign):
            value = node.value
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            if isinstance(node.target, ast.Name):
                target_names = [node.target.id]
        elif isinstance(node, ast.NamedExpr):
            value = node.value
            if isinstance(node.target, ast.Name):
                target_names = [node.target.id]
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Attribute) and func.attr in ("write_session", "text_session"):
                bound_names.update(target_names)
    assert bound_names, "no write_session/text_session binding found -- nothing for WS5d to guard"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "stdout"
            and isinstance(node.value, ast.Name)
            and node.value.id in bound_names
        ):
            pytest.fail(
                f"worker.py reads .stdout off a write_session/text_session "
                f"result at line {node.lineno}"
            )


def test_ws6_attribution_four_cells(backend, env, monkeypatch, tmp_path):
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (bash-shim `CLAUDE_SHIM_SCRIPT_1` scripting) is unreachable dead
    # code -- only the sdk branch's body remains, unconditional.
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write_real")
    counter_file = tmp_path / "ws6-calls"
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(counter_file))

    rid_a = _next_rid()
    seed_pending(env, rid=rid_a)
    target_a = worker.stage_dir() / f"{rid_a}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target_a))
    body_a = _valid_proposal_yaml(env)
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY_1", body_a)
    result_a = worker.run(env.home)
    installed_a = env.proposals / f"{rid_a}.yaml"
    assert installed_a.is_file()
    assert result_a.proposed == [rid_a]
    assert _installed_matches_written(body_a, installed_a.read_text(encoding="utf-8"))

    rid_b = _next_rid()
    seed_pending(env, rid=rid_b)
    outside = tmp_path / "ws6-sdk-outside.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(outside))
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY_2", "denied body\n")
    result_b = worker.run(env.home)
    assert not outside.exists()
    assert not (env.proposals / f"{rid_b}.yaml").exists()
    assert list(worker.stage_dir().iterdir()) == []
    assert result_b.status == "failed"


# ===================================================================== #
# RP -- the repair round
# ===================================================================== #


def test_rp1_repair_round_wiring(request, monkeypatch, env):
    """U-cleanup-B COLLAPSE + RE-BASELINE (§8.4b): the settings-file
    identity this test named was recovered from argv (`--settings
    <path>`) -- there is no argv anymore (`worker.build_argv` deleted,
    §8.1; `FakeBackend.argvs` renamed `.doctrines`, CL9). Rebased onto
    the real call site's own on-disk artifacts: the BATCH round writes
    no settings file at all (`worker.write_settings_file` deleted,
    `WS1`'s own re-baseline above).

    FW-117 RE-BASELINE (2026-08-28): the REPAIR round now ALSO writes no
    settings file -- `worker.write_repair_settings_file` is DELETED, not
    merely unread; it was a dead write nothing under the sdk backend ever
    read back (`options_kwargs()` passes `settings=None` unconditionally,
    `A-2`; the cli-era `--settings <path>` reader left with `CliBackend`).
    Positive control: at base `61c30b3` this test's last line was `assert
    (worker.cache_dir() / "worker.repair.settings.json").exists()` --
    see `git show 61c30b3:plugins/self-learn/cli/tests/test_worker_
    contract.py` around this test. The wiring assertions above (surface
    names, `write_exact`/`write_globs` off the real `SessionSpec.
    containment`) are unchanged and already prove the repair round ran
    for real -- the NEW final assertion below is the mutation-detecting
    one: reintroduce the deleted call and this reddens."""
    monkeypatch.setenv("SELF_LEARN_REPAIR", "1")
    rid = _next_rid()
    seed_pending(env, rid=rid)
    refusable = _dump_yaml(_t4_missing_target(env, rid))
    fixed = _dump_yaml(_t4_target_fixed(env, rid))
    target = worker.stage_dir() / f"{rid}.yaml"
    fake = install_fake(request, monkeypatch, [
        Writes({target: refusable}),
        Writes({target: fixed}),
    ])
    worker.run(env.home)
    assert len(fake.specs) == 2
    assert fake.specs[0].surface == "worker"
    assert fake.specs[1].surface == "worker-repair"
    assert fake.specs[1].containment.write_exact == (str(target),)
    assert fake.specs[1].containment.write_globs == ()
    assert not (worker.cache_dir() / "worker.settings.json").exists()
    assert not (worker.cache_dir() / "worker.repair.settings.json").exists()


def test_rp1a_repair_round_writes_no_settings_artifact_under_cache_dir(request, monkeypatch, env):
    """FW-117 (2026-08-28) -- the dedicated no-settings-file contract
    test the finding's disposition calls for: a real, model-producing
    repair round (same shape as `test_rp1` above) must leave NO new
    settings-shaped artifact anywhere under `worker.cache_dir()`, not
    only at the one literal path `worker.write_repair_settings_file`
    used to write. Snapshots the cache dir's contents BEFORE the run
    (it already holds `worker.log` and friends from the batch round) and
    asserts no NEW entry with "settings" in its name appears after --
    catching a reintroduced write under the OLD exact name (`worker.
    repair.settings.json`, `test_rp1`'s own assertion) as well as a
    renamed one this test's own glob would otherwise miss. Mutation:
    reintroducing `write_repair_settings_file`'s call at the repair call
    site (`worker.py`, inside `run()`'s repair branch) reddens this --
    verified live during this unit's build (temporarily reinstated a
    one-line `_p("worker.repair.settings.json").write_text(...)` at the
    call site, confirmed RED, reverted; see the build report)."""
    rid = _next_rid()
    seed_pending(env, rid=rid)
    refusable = _dump_yaml(_t4_missing_target(env, rid))
    fixed = _dump_yaml(_t4_target_fixed(env, rid))
    target = worker.stage_dir() / f"{rid}.yaml"
    fake = install_fake(request, monkeypatch, [
        Writes({target: refusable}),
        Writes({target: fixed}),
    ])
    cache_dir = worker.cache_dir()
    before = {p.name for p in cache_dir.iterdir()} if cache_dir.is_dir() else set()

    worker.run(env.home)

    assert len(fake.specs) == 2
    assert fake.specs[1].surface == "worker-repair"  # the repair round really ran
    after = {p.name for p in cache_dir.iterdir()}
    new_entries = after - before
    settings_like = {name for name in new_entries if "settings" in name}
    assert settings_like == set(), (
        f"repair round wrote settings-shaped artifact(s) under cache_dir(): {settings_like}"
    )


def test_rp2_repair_reaches_same_backend(backend, env, monkeypatch, tmp_path):
    assert (
        invocation.SELECTOR_FOR_SURFACE["worker-repair"]
        == invocation.SELECTOR_FOR_SURFACE["worker"]
        == "WORKER"
    )
    resolved: list[tuple[str, type]] = []
    real_backend_for = invocation.registry.backend_for

    def spy(surface, **kw):
        b = real_backend_for(surface, **kw)
        resolved.append((surface, type(b)))
        return b

    monkeypatch.setattr(invocation.registry, "backend_for", spy)

    rid = _next_rid()
    seed_pending(env, rid=rid)
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (bash-shim `CLAUDE_SHIM_SCRIPT_1`/`_2` scripting) is unreachable
    # dead code -- only the sdk branch's body remains, unconditional.
    target = worker.stage_dir() / f"{rid}.yaml"
    counter_file = tmp_path / "rp2-calls"
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write_real")
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target))
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(counter_file))
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY_1", _dump_yaml(_t4_missing_target(env, rid)))
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY_2", _dump_yaml(_t4_target_fixed(env, rid)))

    worker.run(env.home)
    worker_calls = [b for s, b in resolved if s == "worker"]
    repair_calls = [b for s, b in resolved if s == "worker-repair"]
    assert worker_calls and repair_calls
    assert worker_calls[-1] is repair_calls[-1]


def test_rp3_repair_surface_direct_drive(backend, tmp_path, monkeypatch):
    """U-cleanup-B COLLAPSE + RE-BASELINE (§8.4b): drop the `build_argv`
    construction -- `_invoke_claude` no longer takes an argv parameter
    at all (§7, `S-46`)."""
    home = tmp_path / "rp3-home"
    home.mkdir()
    member = home / "pending" / "lrn-repair-member.md"
    member.parent.mkdir(parents=True)
    sibling = home / "pending" / "lrn-repair-sibling.md"

    containment = invocation.containment_for(
        "worker-repair",
        allowed_tools=worker.ALLOWED_TOOLS,
        disallowed_tools=worker.DISALLOWED_TOOLS,
        write_exact=(str(member),),
        enforce=True,
    )

    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (bash-shim `CLAUDE_SHIM_EXIT_1`) is unreachable dead code -- only
    # the sdk branch's body remains, unconditional.
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "error_result")

    result = worker._invoke_claude(
        "prompt", worker.repair_timeout_secs(), home,
        label="repair ", containment=containment,
    )
    assert result is None
    assert any(l.startswith("run: repair claude exited") for l in logged), logged

    if backend.param == "sdk":
        cb = charter_mod.build_can_use_tool(containment)
        allow = _call_cb(cb, "Write", {"file_path": str(member)})
        deny = _call_cb(cb, "Write", {"file_path": str(sibling)})
        assert isinstance(allow, PermissionResultAllow)
        assert isinstance(deny, PermissionResultDeny)


def test_rp4_sdk_repair_round_end_to_end(env, sdk_cli_path, monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write_real")
    counter_file = tmp_path / "rp4-calls"
    monkeypatch.setenv("FAKE_CLAUDE_CALLS", str(counter_file))

    rid = _next_rid()
    seed_pending(env, rid=rid)
    target = worker.stage_dir() / f"{rid}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target))
    refusable = _dump_yaml(_t4_missing_target(env, rid))
    fixed = _dump_yaml(_t4_target_fixed(env, rid))
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY_1", refusable)
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY_2", fixed)

    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    captured = _spy_write_session(monkeypatch)

    result = worker.run(env.home)

    assert int(counter_file.read_text(encoding="utf-8").strip()) == 2  # (1)
    worker_repair_calls = [c for c in captured if c.spec.surface == "worker-repair"]
    assert worker_repair_calls, "the second invocation never ran under worker-repair"  # (2)
    assert any(
        "1 refused, 1 eligible, 0 not repairable" in l for l in logged
    ), logged

    installed = env.proposals / f"{rid}.yaml"
    assert installed.is_file()
    installed_bytes = installed.read_text(encoding="utf-8")
    assert not _installed_matches_written(refusable, installed_bytes)  # (3)
    assert _installed_matches_written(fixed, installed_bytes)  # (4)
    assert rid in result.proposed


# ===================================================================== #
# TO -- timeout semantics
# ===================================================================== #


def test_to1_batch_timeout_bounds_both_backends(backend, env, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "1.5")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (armed `CLAUDE_SHIM_SLEEP_1`) is unreachable dead code -- only the
    # sdk branch's body remains, unconditional.
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")

    seed_pending(env, rid=_next_rid())
    start = time.monotonic()
    with _Watchdog(1.5 * 8):  # BLOCKER-2 -- interrupts, does not just measure
        result = worker.run(env.home)
    elapsed = time.monotonic() - start
    assert elapsed <= 1.5 * 8, elapsed  # NOTE-2/M31 -- the mandatory outer bound
    assert result is not None
    matching = [l for l in logged if l == "run: claude timed out after 1.5s"]
    assert matching, logged


def test_to2_repair_timeout_bounds_both_backends(backend, tmp_path, monkeypatch):
    """U-cleanup-B COLLAPSE + RE-BASELINE (§8.4b): drop the `build_argv`
    construction -- `_invoke_claude` no longer takes an argv parameter
    at all (§7, `S-46`)."""
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "1.2")
    home = tmp_path / "to2-home"
    home.mkdir()
    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (armed `CLAUDE_SHIM_SLEEP_1`) is unreachable dead code -- only the
    # sdk branch's body remains, unconditional.
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")

    start = time.monotonic()
    with _Watchdog(1.2 * 8):  # BLOCKER-2 -- interrupts, does not just measure
        result = worker._invoke_claude(
            "prompt", worker.repair_timeout_secs(), home,
            label="repair ", containment=invocation.DEGRADED_WORKER_CONTAINMENT,
        )
    elapsed = time.monotonic() - start
    assert elapsed <= 1.2 * 8, elapsed
    assert result is None
    assert "run: repair claude timed out after 1.2s" in logged


def test_to3_timeouts_independent_t1(request, monkeypatch, env):
    monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "37")
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "53")
    rid = _next_rid()
    seed_pending(env, rid=rid)
    target = worker.stage_dir() / f"{rid}.yaml"
    fake = install_fake(request, monkeypatch, [
        Writes({target: _dump_yaml(_t4_missing_target(env, rid))}),
        Writes({target: _dump_yaml(_t4_target_fixed(env, rid))}),
    ])
    worker.run(env.home)
    assert [s.timeout for s in fake.specs] == [37.0, 53.0]


def test_to3_timeouts_independent_transport(backend, env, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "1.2")
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "90")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (armed `CLAUDE_SHIM_SLEEP_1`) is unreachable dead code -- only the
    # sdk branch's body remains, unconditional.
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")
    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    seed_pending(env, rid=_next_rid())
    start = time.monotonic()
    with _Watchdog(1.2 * 8):  # BLOCKER-2 -- interrupts, does not just measure
        worker.run(env.home)
    elapsed = time.monotonic() - start
    # if the batch surface leaked the repair bound (90s), this would blow
    # well past 1.2*8=9.6s.
    assert elapsed <= 1.2 * 8, elapsed
    assert any("run: claude timed out after 1.2s" in l for l in logged), logged


# ===================================================================== #
# FL -- the failure legs
# ===================================================================== #


def test_fl1_failure_legs_never_raise(tmp_path, backend):
    # `FL-c`/`FR2`: this criterion is declared `(T2 + T3)` in Sec.4, so it
    # is parametrized over the `backend` fixture rather than looping over
    # both params internally -- that is what gives the module's collected
    # node ids a `[cli]` and a `[sdk]` entry for FR2 to find. Splitting by
    # param also STRENGTHENS `F-b`'s enumeration: `driven` is checked for
    # THIS param alone, so a kind missing from one backend's coverage can
    # no longer be masked by the other backend's iteration sharing one set.
    #
    # MAJOR-1 (code-gate fold): `driven` is now built from the SPY's
    # OBSERVED `Outcome.failure`, never from the loop variable `kind`
    # itself -- adding the loop variable unconditionally after a call
    # that never raises (`M-a`) is vacuous: it would record a bogus
    # sixth `FAILURE_KINDS` member (`M16`) as "driven" even though
    # nothing in `_apply_failure_env` has a recipe for it and no real
    # failure of that shape ever occurred.
    driven: set[str] = set()
    for kind in invocation.FAILURE_KINDS:
        mp = pytest.MonkeyPatch()
        try:
            captured = _spy_write_session(mp)
            home = tmp_path / f"fl1-{backend.param}-{kind}"
            home.mkdir()
            timeout = _apply_failure_env(kind, backend.param, scratch=home, monkeypatch=mp)
            containment = _worker_containment(home)
            if kind == "os-error" and backend.param == "sdk":
                containment = dataclasses.replace(containment, write_globs=("/tmp/[bad/**",))
            with _Watchdog(timeout * 8):  # MAJOR-A (code-gate fold) -- bounds the sdk/timeout cell (M31), same as TO's BLOCKER-2
                result = worker._invoke_claude(
                    "PROMPT", timeout, home, label="", containment=containment
                )
            assert result is None
            assert captured, f"no session recorded for kind={kind}"
            observed = captured[-1].outcome.failure
            assert observed == kind, (kind, observed)
            driven.add(observed)
        finally:
            mp.undo()
    assert driven == set(invocation.FAILURE_KINDS)  # F-b -- the fail-closed enumeration, per backend


def _drive_fl2_lines(tmp_path: Path, marker_templates) -> dict[str, list[str]]:
    """U-cleanup-A COLLAPSE + RE-BASELINE (§8.4b, `test_fl2_byte_
    identity_and_provenance[sdk]`, "the single most important test
    disposition"): the `param` argument is gone -- this always drove the
    `sdk` leg for real ANYWAY (`FL-c`'s byte-identity clause explicitly
    "rides the sdk param leg"), and the `cli` leg it used to ALSO drive
    (to compare against) reached a real `CliBackend`, a path `AG1`'s
    tripwire now makes fatal.

    DIVERGENCE-1 fold (code gate r1, 8uvjHmdKaUd6PI3tSyB-F): the
    `worker.build_argv` call is ALSO gone now, not just the deleted
    second (`cli`-param) call. `_invoke_claude`'s signature still takes
    a positional `argv` (`worker.py:3121`), which it closes over as
    `cli_argv_builder=lambda _settings: argv` -- structurally required,
    but its VALUE is inert under sdk (the sdk transport never calls
    `cli_argv_builder` at all; only the CliBackend leg this test no
    longer drives would have). Calling `worker.build_argv` just to
    satisfy that unused parameter kept a real dependency on CL9's own
    deletion target alive in an sdk-only test path -- replaced by the
    same trivial literal the real sdk-only call sites already use
    (`test_hd4_seam_is_total_on_the_analyst_surface`'s `cli_argv_
    builder=lambda _s: ["claude", "-p", "p"]`, `test_u_sdka.py`).

    U-cleanup-B follow-on: that inert literal argv is ALSO gone now --
    `_invoke_claude`'s signature dropped the `argv` parameter entirely
    (§7, `S-46`), so there is nothing left to close over, inert or
    otherwise."""
    results: dict[str, list[str]] = {}
    for kind in invocation.FAILURE_KINDS:
        mp = pytest.MonkeyPatch()
        try:
            home = tmp_path / f"fl2-sdk-{kind}"
            home.mkdir()
            logged: list[str] = []
            mp.setattr(worker, "log", lambda msg, _l=logged: _l.append(msg))
            mp.setitem(invocation.LOG_TEMPLATES, "worker", marker_templates)

            timeout = _apply_failure_env(kind, "sdk", scratch=home, monkeypatch=mp)
            containment = _worker_containment(home)
            if kind == "os-error":
                containment = dataclasses.replace(containment, write_globs=("/tmp/[bad/**",))

            with _Watchdog(timeout * 8):  # MAJOR-A (code-gate fold) -- bounds the sdk/timeout cell (M31), same as TO's BLOCKER-2
                worker._invoke_claude("PROMPT", timeout, home, label="", containment=containment)
            results[kind] = list(logged)
        finally:
            mp.undo()
    return results


def test_fl2_byte_identity_and_provenance(tmp_path, backend):
    # `FL-c`/`FR2`: declared `(T2 + T3)`. U-cleanup-A COLLAPSE (§8.4b):
    # the `cli` param leg and the cross-backend byte-identity comparison
    # it fed are gone (see `_drive_fl2_lines`'s own docstring) -- what
    # remains is the provenance-and-shape clause, which was already
    # per-param and needed no cli comparison to hold.
    original = invocation.LOG_TEMPLATES["worker"]
    marker_templates = dataclasses.replace(
        original,
        exited=f"MARKER-EXITED {original.exited}",
        timed_out=f"MARKER-TIMEOUT {original.timed_out}",
        not_found=f"MARKER-NOTFOUND {original.not_found}",
        os_error=f"MARKER-OSERROR {original.os_error}",
        unavailable=f"MARKER-UNAVAIL {original.unavailable}",
    )

    own = _drive_fl2_lines(tmp_path, marker_templates)

    # provenance and shape, for all five. FW-108 (U-opsfix) closed the
    # os-error/sdk cell's old exception (it used to be silent by
    # construction, "R-10") -- the CharterPatternUnsupported leg now
    # renders `templates.os_error` exactly like every other cell here.
    for kind in invocation.FAILURE_KINDS:
        lines = own[kind]
        assert lines, (backend.param, kind)
        assert any("MARKER-" in l for l in lines), (backend.param, kind, lines)

    # exit: shape only -- rc is synthesized on sdk.
    exit_line = own["exit"][0]
    assert re.match(r"^MARKER-EXITED run: claude exited 1: ", exit_line), exit_line


def test_fl3_run_survives_every_failure(tmp_path, backend):
    # `FL-c`/`FR2`: declared `(T2 + T3)`, parametrized over `backend`.
    for kind in invocation.FAILURE_KINDS:
        mp = pytest.MonkeyPatch()
        try:
            sub = tmp_path / f"fl3-{backend.param}-{kind}"
            sub.mkdir()
            scratch = sub / "scratch"
            scratch.mkdir()
            e = Env(sub / "ledger-root")
            mp.setenv("SELF_LEARN_HOME", str(e.home))
            mp.setenv("SELF_LEARN_REPAIR", "0")
            seed_pending(e, rid=_next_rid())
            timeout = _apply_failure_env(kind, backend.param, scratch=scratch, monkeypatch=mp)

            last_run = worker.cache_dir() / "worker.last-run"
            existed_before = last_run.exists()
            mtime_before = last_run.stat().st_mtime if existed_before else None

            with _Watchdog(timeout * 8):  # MAJOR-A (code-gate fold) -- bounds the sdk/timeout cell (M31), same as TO's BLOCKER-2
                result = worker.run(e.home)

            assert result is not None
            assert result.status == "failed", (backend.param, kind, result.status)
            if existed_before:
                assert last_run.stat().st_mtime == mtime_before
            else:
                assert not last_run.exists()
        finally:
            mp.undo()


# ===================================================================== #
# HA -- the enforcement hatch
# ===================================================================== #


def test_ha1_hatch_open_omits_default_mode(env, sdk_fake_worker, monkeypatch):
    """U-cleanup-B RE-BASELINE: the BATCH round's on-disk settings file
    (`worker.settings.json`) no longer exists -- `worker.write_
    settings_file` is deleted (§8.1) and the batch round has passed
    `settings=None` to the sdk seam ever since (`WS1`'s own
    re-baseline, above).

    FW-117 RE-BASELINE (2026-08-28): the REPAIR round's file (`worker.
    repair.settings.json`) no longer survives either -- `worker.write_
    repair_settings_file` is DELETED, not merely unread; it was a dead
    write, same reasoning as `write_settings_file` one build earlier
    (`options_kwargs()` passes `settings=None` unconditionally for BOTH
    surfaces, `A-2`). At base `61c30b3` this test's last three lines
    read the file back off disk and asserted `"defaultMode" not in
    repair_settings` -- see `git show 61c30b3:plugins/self-learn/cli/
    tests/test_worker_contract.py` around this test. The property now
    reads off the same real observable the batch leg already used
    (`options_kwargs(spec)["settings"]`, captured by `_spy_write_
    session` regardless of which round it renders for) -- symmetric
    for both surfaces now that neither has a file -- plus a positive,
    mutation-detecting check that the old path stays unwritten.

    Code gate r1 NIT-7: renamed from `test_ha1_cli_hatch_open_omits_
    default_mode` -- the property this test asserts (the enforcement
    hatch omits `defaultMode` when open) holds identically for both
    rounds now, on the one remaining backend; nothing about it is
    `cli`-specific any more, so the name should not say so."""
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")
    rid = _next_rid()
    seed_pending(env, rid=rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid)))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid)))
    captured = _spy_write_session(monkeypatch)
    worker.run(env.home)
    batch_cap = next(c for c in captured if c.spec.surface == "worker")
    repair_cap = next(c for c in captured if c.spec.surface == "worker-repair")
    assert batch_cap.spec.containment.default_mode is None
    assert repair_cap.spec.containment.default_mode is None
    assert batch_cap.kwargs["settings"] is None
    assert repair_cap.kwargs["settings"] is None
    assert not (worker.cache_dir() / "worker.repair.settings.json").exists()


def test_ha2_sdk_hatch_open_three_legs(env, sdk_cli_path, monkeypatch):
    # leg (i): driven end-to-end from the real variable.
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    outside = env.home.parent / "ha2-outside.md"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(outside))
    captured = _spy_write_session(monkeypatch)

    seed_pending(env, rid=_next_rid())
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")
    captured.clear()
    worker.run(env.home)
    open_outcome = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert open_outcome.denials == ()

    seed_pending(env, rid=_next_rid())
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "1")
    captured.clear()
    worker.run(env.home)
    closed_outcome = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert len(closed_outcome.denials) == 1

    # leg (ii): Bash still denied under the hatch.
    c_open = invocation.containment_for(
        "worker", allowed_tools=worker.ALLOWED_TOOLS, disallowed_tools=worker.DISALLOWED_TOOLS,
        home=str(env.home), stage_dir=worker.stage_dir(), stage_on=True, enforce=False,
    )
    cb = charter_mod.build_can_use_tool(c_open)
    assert isinstance(_call_cb(cb, "Bash", {}), PermissionResultDeny)

    # leg (iii): the repair surface opens too, driven directly with a
    # non-empty write_exact.
    repair_open = invocation.containment_for(
        "worker-repair", allowed_tools=worker.ALLOWED_TOOLS, disallowed_tools=worker.DISALLOWED_TOOLS,
        write_exact=(str(env.home / "pending" / "lrn-x.md"),), enforce=False,
    )
    cb2 = charter_mod.build_can_use_tool(repair_open)
    assert isinstance(_call_cb(cb2, "Write", {"file_path": "/anywhere.md"}), PermissionResultAllow)


def test_ha3_hatch_closed_negative_controls(env, monkeypatch, backend):
    # `FL-c`/`FR2`: declared `(T2 + T3)`, parametrized over `backend`
    # (replacing direct `sdk_fake_worker`/`sdk_cli_path` fixture
    # use -- `backend`'s own branches already build the same shim/sdk env,
    # `SU5`'s census updated accordingly). Leg (i) splits by param: the
    # `cli` leg checks the settings-file half, the `sdk` leg checks the
    # denial half -- both are "the variable unset" case the spec's leg (i)
    # names, just observed through each backend's own witness.
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (settings-file `defaultMode` check) is unreachable dead code -- only
    # the sdk branch's body remains, unconditional.
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    outside = env.home.parent / "ha3-outside.md"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(outside))
    captured = _spy_write_session(monkeypatch)
    seed_pending(env, rid=_next_rid())
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    worker.run(env.home)
    outcome = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert len(outcome.denials) == 1
    resolved = str(outside.resolve())
    assert outcome.denials[0]["reason"] == (
        f"self-learn invocation charter: Write write scope does not include {resolved}"
    )

    # legs (ii)-(iii) are "with the variable SET" (`SELF_LEARN_ENFORCE_SCOPE=0`,
    # the open condition `HA1`/`HA2` use) -- without this, `M39`'s
    # environment-reading charter mutant has nothing to read and both legs
    # pass vacuously regardless of which source `hatch_open` derives from,
    # which defeats `C-10`'s falsifiability point (`MAJOR-A`).
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")

    # leg (ii): the miner containment still denies with the variable set.
    c_miner = invocation.containment_for(
        "miner-reader", disallowed_tools=worker.DISALLOWED_TOOLS, spool_dir="/tmp/spool"
    )
    cb_m = charter_mod.build_can_use_tool(c_miner)
    assert isinstance(_call_cb(cb_m, "Write", {"file_path": "/outside/spool.txt"}), PermissionResultDeny)

    # leg (iii): DEGRADED_WORKER_CONTAINMENT grants nothing.
    cb_d = charter_mod.build_can_use_tool(invocation.DEGRADED_WORKER_CONTAINMENT)
    assert isinstance(_call_cb(cb_d, "Write", {"file_path": "/anything.md"}), PermissionResultDeny)


def test_ha4_the_fence_and_silence(backend, env, monkeypatch):
    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    # U-cleanup-B DELETE (§8.3): the `if backend.param == "cli":` branch
    # (settings-file `allow`-list + ARGV byte-identity check) is
    # unreachable dead code -- only the sdk branch's body remains,
    # unconditional.
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_text")
    captured = _spy_write_session(monkeypatch)
    options_by_scope = {}
    for scope in ("1", "0"):
        monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", scope)
        logged.clear()
        captured.clear()
        seed_pending(env, rid=_next_rid())
        worker.run(env.home)
        spec = [c.spec for c in captured if c.spec.surface == "worker"][-1]
        options_by_scope[scope] = backend_mod.options_kwargs(spec)
        hatch_lines = [
            l for l in logged
            if "enforce" in l.lower() or "hatch" in l.lower() or "ENFORCE_SCOPE" in l
        ]
        assert hatch_lines == []
    on, off = options_by_scope["1"], options_by_scope["0"]
    assert on["permission_mode"] == "default" == off["permission_mode"]
    assert on["setting_sources"] == [] == off["setting_sources"]
    assert on["strict_mcp_config"] is True and off["strict_mcp_config"] is True
    assert on["settings"] is None and off["settings"] is None
    assert on["disallowed_tools"] == off["disallowed_tools"]


# ===================================================================== #
# BG -- the >128 KiB prompt
# ===================================================================== #

#: `BG-a` -- deterministic, asserted against the 128 KiB threshold in
#: the criterion itself (a later shrink reddens rather than silently
#: weakening every leg that uses it).
BIG_PROMPT = "self-learn worker contract >128KiB prompt fixture: " + ("x" * 170_000)


def test_bg1_prompt_not_in_argv(backend, tmp_path, monkeypatch):
    # BLOCKER-1 (code-gate fold): re-routed through `worker._invoke_claude`
    # -- the hand-built `_spec_for`/`write_session` drive never exercised
    # the worker's OWN prompt handling, so a mutation truncating the
    # prompt INSIDE `_invoke_claude` (`M12`) was invisible to this group.
    # U-cleanup-B rebase (§8.1): there is no argv anymore (`_bg_argv`/
    # `worker.build_argv` deleted) -- the property this test names ("the
    # prompt never reaches argv") now means "the prompt appears in none
    # of `options_kwargs`'s values" (the `test_hd7`/`test_wr1`-shaped
    # check), since `options_kwargs` is everything the sdk seam actually
    # sends onward.
    assert len(BIG_PROMPT.encode("utf-8")) > 128 * 1024
    home = tmp_path / "bg1-home"
    home.mkdir()
    captured = _spy_write_session(monkeypatch)
    containment = _worker_containment(home)
    worker._invoke_claude(BIG_PROMPT, 20.0, home, label="", containment=containment)
    cap = captured[-1]
    for value in cap.kwargs.values():
        assert BIG_PROMPT not in repr(value)


# U-cleanup-A DELETE (§8.4, "CLI-only named tests outside the
# parametrization"; §10.2's non-parametrized census): `test_bg2_cli_
# prompt_delivered_intact_on_stdin` forced `SELF_LEARN_BACKEND_WORKER=
# cli` and drove `worker._invoke_claude` through a REAL `CliBackend` ->
# subprocess-on-PATH transport -- the migrated `sdk_fake_worker`
# fixture no longer shims anything onto PATH (it routes through
# `SdkBackend` -> `fake_claude.py` instead), so the test measurably
# broke the moment the fixture migrated: `delivered` came back `''`
# instead of `BIG_PROMPT`, because there was no real "claude" left on
# PATH for `CliBackend` to invoke. Its subject (CLI-transport stdin
# delivery for a >128 KiB prompt) is fully replaced by
# `test_bg3_sdk_prompt_delivered_intact` below, which asserts the same
# property against the real sdk transport via a `ClaudeSDKClient.query`
# spy.


def test_bg3_sdk_prompt_delivered_intact(sdk_cli_path, tmp_path, monkeypatch):
    # BLOCKER-1: routed through `worker._invoke_claude` (see BG1); the
    # outcome now comes from the `M-c1` spy since `_invoke_claude` never
    # returns one itself.
    assert len(BIG_PROMPT.encode("utf-8")) > 128 * 1024
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    home = tmp_path / "bg3-home"
    home.mkdir()

    recorded_prompts: list[str] = []
    real_query = ClaudeSDKClient.query

    async def spy_query(self, prompt, *a, **kw):
        recorded_prompts.append(prompt)
        return await real_query(self, prompt, *a, **kw)

    monkeypatch.setattr(ClaudeSDKClient, "query", spy_query)
    captured = _spy_write_session(monkeypatch)

    containment = _worker_containment(home)
    worker._invoke_claude(BIG_PROMPT, 20.0, home, label="", containment=containment)
    outcome = captured[-1].outcome

    assert recorded_prompts and recorded_prompts[0] == BIG_PROMPT  # witness (i)
    assert repr(BIG_PROMPT) in outcome.detail  # witness (ii)
    assert len(outcome.detail) == 30 + len(repr(BIG_PROMPT))


# ===================================================================== #
# EV -- tool-events capture
# ===================================================================== #


def test_ev1_events_file_written_under_sdk(env, sdk_cli_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    files = _worker_events_files()
    assert len(files) == 1
    run_id = files[0].name[len("worker.tool-events."):-len(".jsonl")]
    assert re.match(r"^\d{8}T\d{6}Z-\d+$", run_id)
    lines = [
        json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert lines[0]["type"] == "meta"
    assert lines[0]["surface"] == "worker"
    assert lines[0]["session_id"] == "fake-session-1"


def test_ev2_events_file_carries_tool_events(env, sdk_cli_path, monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    target = tmp_path / "ev2-target.md"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target))
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    events = _latest_worker_events()
    tool_use = [e for e in events if e.get("kind") == "tool_use"]
    assert tool_use and tool_use[0]["name"] == "Write"
    assert tool_use[0]["input"]["file_path"] == str(target)
    tool_result = [e for e in events if e.get("kind") == "tool_result"]
    assert tool_result


def test_ev3_denial_pair_both_directions(env, sdk_cli_path, monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")

    outside = tmp_path / "ev3-outside.md"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(outside))
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    events = _latest_worker_events()
    denials = [e for e in events if e.get("type") == "denial"]
    assert len(denials) == 1
    assert denials[0]["source"] == "charter" and denials[0]["tool"] == "Write"
    tool_result = [e for e in events if e.get("kind") == "tool_result"][0]
    assert tool_result["is_error"] is True

    inside = worker.stage_dir() / "ev3b.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(inside))
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    events2 = _latest_worker_events()
    denials2 = [e for e in events2 if e.get("type") == "denial"]
    assert denials2 == []
    tool_result2 = [e for e in events2 if e.get("kind") == "tool_result"][0]
    assert tool_result2["content"] == "ok"


#: gate r1 B-1: the literal FW-107 log line, byte-pinned. This is
#: worker.py's ONLY permitted occurrence of the substring "tool-events"
#: -- see `test_ev4_tool_events_string_confined_to_events_module`.
_EV4_FW107_PINNED_FRAGMENT = 'f"worker*.tool-events.*.jsonl in {cache_dir()}"'


def test_ev4_tool_events_string_confined_to_events_module():
    """EV4's actual property: exactly one module DEFINES the
    `tool-events` filename convention -- `invocation_sdk/events.py`
    (`_event_log_path`/`prune_event_logs`'s pattern).

    Gate r1 B-1: the prior fold's narrowing was a whole-FILE exemption
    (`path in allowed`) -- the gate proved it unenforced: a real
    `_gate_probe_tool_events_path()` appended to worker.py stayed
    green, and the SAME probe appended to miner.py also went green
    (the check only ever looked at which FILE the substring was in,
    never how many times or where). Replaced with the narrowest pin
    that actually admits FW-107 and rejects that probe: worker.py may
    contain the literal substring "tool-events" EXACTLY ONCE, and that
    one occurrence must be the pinned FW-107 log-line fragment itself
    (asserted on the literal text, not just presence/count) --
    `events.py` remains the unrestricted definer, and every OTHER
    module (miner.py included) is held to the original zero-occurrence
    confinement rule."""
    src_root = Path(inspect.getfile(worker)).parent
    events_path = src_root / "invocation_sdk" / "events.py"
    worker_path = src_root / "worker.py"

    assert "tool-events" in events_path.read_text(encoding="utf-8"), (
        "the definer itself has nothing to pin -- EV4 would be vacuous"
    )

    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        count = text.count("tool-events")
        if path == events_path:
            continue  # the definer -- unrestricted
        if path == worker_path:
            assert count == 1, (
                f"worker.py must contain 'tool-events' EXACTLY ONCE (the "
                f"pinned FW-107 log line) -- found {count} occurrence(s)"
            )
            assert _EV4_FW107_PINNED_FRAGMENT in text, (
                "worker.py's one 'tool-events' occurrence has drifted off "
                f"the pinned FW-107 log line: {_EV4_FW107_PINNED_FRAGMENT!r}"
            )
            continue
        assert count == 0, (
            f"'tool-events' substring found outside "
            f"{{{events_path}, {worker_path}}}: {path}"
        )


# U-cleanup-A DELETE (§8.4, "CLI-only named tests outside the
# parametrization"; §10.2's non-parametrized census): `test_ev5_cli_
# leaves_no_events_file` asserted the CLI transport produces no
# `tool-events` file (`EV4`'s own finding: that string is confined to
# `invocation_sdk/events.py`, an sdk-only module). The migrated
# `sdk_fake_worker` fixture routes `worker.run()` through
# `SdkBackend` unconditionally now, so the property under test --
# "a CLI-transport run leaves no events file" -- has no reachable
# subject left to exercise; the positive property (an sdk-transport run
# DOES write one) is already covered by `test_ev1_events_file_written_
# under_sdk` above.


# ===================================================================== #
# FR -- flip readiness, not flip
# ===================================================================== #


# U-cleanup-B DELETE (§8.4b, "CLI-only named tests" class):
# `test_fr1_backend_worker_cli_resolves_both_surfaces` asserted that a
# WORKER selector pinned to `cli` resolves BOTH `worker` and
# `worker-repair` to a real `CliBackend` -- `CliBackend` no longer
# exists (§8.1) and a `cli` pin now REFUSES (`SEL1`-`SEL4`), so this
# outcome is neither reachable nor a legitimate PASS to assert. The
# scoping property it protected (the WORKER selector governs BOTH
# worker surfaces) is still covered structurally by `SELECTOR_FOR_
# SURFACE["worker-repair"] == SELECTOR_FOR_SURFACE["worker"]`
# (`test_bk2_selector_mapping_holds`, `test_provider.py`) and
# behaviourally by `test_fr4_selector_mapping_does_not_cross_govern`
# below.


def test_fr3_default_is_now_sdk(tmp_path, monkeypatch, sdk_absent):
    # U-flip: this criterion was `test_fr3_default_stays_cli` -- the
    # worker/worker-repair default flipped from "cli" to "sdk" (same
    # in-code table rung the analyst flip (U-sdka) used). `sdk_absent`
    # forces the SDK import to fail so the resolved backend is asserted
    # by the failure mode (`BackendUnavailable`), not by a real
    # `SdkBackend` construction depending on the host's installed extra.
    for var in ("SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER", "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "fr3-home"
    home.mkdir()

    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("worker", home=home)
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("worker-repair", home=home)
    # U-cleanup-B: KNOWN_BACKENDS has one member now (§8.1) -- "cli" is
    # deleted, not merely a second choice this surface avoids.
    assert invocation.KNOWN_BACKENDS == ("sdk",)
    # instrument half: `git diff 89f8ef7..HEAD -- .../registry.py` empty
    # -- recorded in the build report, not asserted here (`FL-b`).


def test_fr4_selector_mapping_does_not_cross_govern(tmp_path, monkeypatch):
    home = tmp_path / "fr4-home"
    home.mkdir()
    for var in ("SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER", "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST"):
        monkeypatch.delenv(var, raising=False)

    from self_learn.invocation_sdk import SdkBackend as _IndependentSdkBackend

    # U-flip flipped worker/worker-repair/miner-reader's product default
    # to sdk (same table rung the analyst flip, U-sdka, used). The
    # scoping claim (the MINER/ANALYST selectors do not govern WORKER)
    # needs the foreign stimulus INVERTED to "cli": a leak would then
    # flip worker to CliBackend and redden, while the correct behavior
    # keeps its own sdk default. (Stimulus "sdk" would be tautological --
    # leak and no-leak both resolve SdkBackend; gate blessing-read catch.)
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    assert type(invocation.backend_for("worker", home=home)) is _IndependentSdkBackend
    assert type(invocation.backend_for("worker-repair", home=home)) is _IndependentSdkBackend
    monkeypatch.delenv("SELF_LEARN_BACKEND_MINER")
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")

    # Same inversion for the WORKER -> miner-reader leg: miner-reader's
    # own default is now sdk too, so the foreign stimulus is "cli".
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    assert type(invocation.backend_for("miner-reader", home=home)) is _IndependentSdkBackend
    # U-sdka flipped the analyst's product default to sdk. The scoping
    # claim (the WORKER selector does not govern the analyst) needs the
    # foreign stimulus INVERTED to "cli": a leak would then flip the
    # analyst to CliBackend and redden, while the correct behavior keeps
    # its own sdk default. (Stimulus "sdk" would be tautological -- leak
    # and no-leak both resolve SdkBackend; gate blessing-read catch.)
    # `SELF_LEARN_BACKEND_WORKER` is already "cli" from the miner-reader
    # leg above -- same foreign stimulus serves both legs.
    assert type(invocation.backend_for("analyst", home=home)) is _IndependentSdkBackend


# ===================================================================== #
# HY -- hygiene
# ===================================================================== #


def test_hy1_no_claude_argv_literal_without_invoke_claude():
    src = Path(__file__).read_text(encoding="utf-8")
    pattern = re.compile(r'\[\s*"claude"\s*\]')
    for i, line in enumerate(src.splitlines(), start=1):
        if pattern.search(line):
            assert "worker._invoke_claude(" in line, (i, line)


def test_hy2_sdk_sessions_always_use_the_fake():
    # this function's own body self-matches the literals it scans for
    # (the `_HG2_SELF` trap `test_invocation_sdk.py`'s `HY2` precedent
    # names) -- scan the module with THIS function's body blanked.
    scanned = _module_source_excluding("test_hy2_sdk_sessions_always_use_the_fake")
    assert "SdkBackend(" not in scanned
    assert "ClaudeSDKClient(" not in scanned

    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    # `_apply_failure_env` is the third sanctioned setter: it is the ONE
    # place that DELIBERATELY points SELF_LEARN_SDK_CLI_PATH at a
    # nonexistent path for the "not-found" kind (F-c's own recipe) rather
    # than at the shipped fake -- reviewed, single-purpose, never ad hoc.
    sanctioned = {"backend", "_build_sdk_env", "_apply_failure_env"}
    setters = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setenv"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "SELF_LEARN_SDK_CLI_PATH"
        ):
            setters.append(node)

    def _enclosing_func(target):
        best = None
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.lineno <= target.lineno <= (fn.end_lineno or fn.lineno):
                if best is None or fn.lineno > best.lineno:
                    best = fn
        return best

    assert setters, "no SELF_LEARN_SDK_CLI_PATH setter found -- HY2 has nothing to pin"
    for setter in setters:
        fn = _enclosing_func(setter)
        assert fn is not None and fn.name in sanctioned, (
            f"SELF_LEARN_SDK_CLI_PATH set outside the sanctioned setters at line {setter.lineno}"
        )


def test_hy3_tripwire_untouched_and_live():
    conftest_path = _repo_root() / "plugins/self-learn/cli/tests/conftest.py"
    sha = hashlib.sha256(conftest_path.read_bytes()).hexdigest()
    assert sha == _ARMOR_SHAS["plugins/self-learn/cli/tests/conftest.py"]

    import claude_agent_sdk._internal.transport.subprocess_cli as subprocess_cli

    with pytest.raises(AssertionError, match=r"claude_agent_sdk\._find_cli\(\) was called"):
        subprocess_cli.SubprocessCLITransport._find_cli(None)


def test_hy4_no_writes_outside_tmp_path_or_xdg(env, sdk_cli_path, monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    files = _worker_events_files()
    assert files
    resolved = files[0].resolve()
    assert str(resolved).startswith(str(tmp_path.resolve())), resolved

    scanned = _module_source_excluding("test_hy4_no_writes_outside_tmp_path_or_xdg")
    assert "Path.home()" not in scanned
    assert ".self-learn" not in scanned


# U-cleanup-A DELETE (§8.4 table, "CLI-only named tests outside the
# parametrization"): `test_hy5_cli_side_no_real_claude_control` forced
# `SELF_LEARN_BACKEND_WORKER=cli`, resolved `claude` off PATH, and drove
# a REAL `worker._invoke_claude` -> `CliBackend._run` call -- exactly
# the transport `AG1`'s tripwire now makes unreachable by design. Its
# sdk-side counterpart (no real credentialed spawn, os-error handling
# through the sdk transport) is covered by `test_hy4_no_writes_outside_
# tmp_path_or_xdg` and `test_tr4_bare_os_error_is_caught_on_analyst_
# worker_and_miner`'s sdk leg (`test_invocation.py`) plus `_no_real_sdk_
# spawn_tripwire` itself (`conftest.py`).
