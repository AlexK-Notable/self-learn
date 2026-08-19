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
from shims import write_worker_claude_shim
from test_worker import (  # noqa: F401 -- fixtures resolved by name
    Env,
    PROPOSAL_YAML_TEMPLATE,
    claude_cli_shim_worker,
    env,
    seed_pending,
    shim_writes,
)
from test_repair import _defect_script, _t4_missing_target, _t4_target_fixed
from test_invocation_sdk import FAKE_CLI, sdk_absent, sdk_cli_path  # noqa: F401

BASE_COMMIT = "89f8ef7"

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
    same-scope fixture (`backend`, `claude_cli_shim_worker`, ...) so its
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


def _build_cli_shim(root: Path, monkeypatch) -> dict:
    """`Par-1`'s cli row / `P-a`: CALLS `shims.write_worker_claude_shim`
    directly (never `request.getfixturevalue("claude_cli_shim_worker")`,
    which would drag a bash shim onto PATH on the `sdk` param too --
    `HY5`) and PREPENDS its directory to the INHERITED PATH (`P-c1`/
    `F-c2`) -- `worker.run()` shells out to `git` before it ever reaches
    an invocation, so a scrubbed PATH kills every `cli`-param criterion
    at `_digest`. STEP 0: installs the decoy shadow first (idempotent;
    the autouse fixture already did this for `root == tmp_path`, this
    call additionally covers `_apply_failure_env`'s per-kind `scratch`
    subdirectories, which are NOT `tmp_path` itself)."""
    _install_decoy_shadow(root, monkeypatch)
    shims_dir = root / "shims"
    shims_dir.mkdir(exist_ok=True)
    counter = root / "claude-count"
    log = root / "claude-argv.log"
    prompt_log = root / "claude-prompt.log"
    calls_dir = root / "claude-calls"
    calls_dir.mkdir(exist_ok=True)
    write_worker_claude_shim(
        shims_dir, counter=counter, log=log, prompt_log=prompt_log, calls_dir=calls_dir
    )
    monkeypatch.setenv("PATH", f"{shims_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    def count() -> int:
        try:
            return int(counter.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return 0

    def call_prompt(n: int) -> str:
        p = calls_dir / f"prompt.{n}"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def argv_for(n: int) -> list[str]:
        p = calls_dir / f"argv.{n}"
        return p.read_text(encoding="utf-8").split("\0")[:-1] if p.exists() else []

    return {"dir": shims_dir, "count": count, "call_prompt": call_prompt, "argv": argv_for}


def _build_sdk_env(monkeypatch) -> None:
    """`Par-1`'s sdk row (`B-5`/`HY3`): the ONLY sanctioned setter of
    `SELF_LEARN_SDK_CLI_PATH` inside this module besides the `backend`
    fixture itself -- `HY2` scans for this."""
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")


@dataclass
class _Backend:
    param: str
    shim: dict | None  # cli only
    fake_cli: Path | None  # sdk only

    def prompt_of(self, n: int) -> str | None:
        """The one shape both legs can answer (`Par-1`); the `sdk` leg
        has no generic per-invocation prompt capture (`BG3` uses its own
        two-witness mechanism instead), so it is honestly `None` here."""
        if self.param == "cli":
            assert self.shim is not None
            return self.shim["call_prompt"](n)
        return None


@pytest.fixture(params=["cli", "sdk"])
def backend(request, tmp_path, monkeypatch):
    """`Par-1` -- the `["cli", "sdk"]` fixture every `(T2 + T3)` criterion
    is parametrized over."""
    if request.param == "cli":
        monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
        shim = _build_cli_shim(tmp_path, monkeypatch)
        return _Backend(param="cli", shim=shim, fake_cli=None)
    # STEP 0 / MAJOR-4 backstop: even on the `sdk` param, re-assert the
    # decoy shadow explicitly here (the autouse fixture already installed
    # it, this call is idempotent) -- the gate's finding was exactly
    # "sdk falls to CliBackend with inherited PATH"; this is the row that
    # makes that fall-through land on the decoy, never the real binary.
    _install_decoy_shadow(tmp_path, monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    _build_sdk_env(monkeypatch)
    assert os.environ.get("SELF_LEARN_SDK_CLI_PATH") == str(FAKE_CLI)  # `PB3`
    return _Backend(param="sdk", shim=None, fake_cli=FAKE_CLI)


#: `MAJOR-3`: a module-level alias captured immediately after the fixture
#: is defined, distinct from the `backend` PARAMETER name every test
#: using the fixture shadows it with -- `PB1` needs the fixture FUNCTION
#: object itself (to read its declared `params` off the pytest marker),
#: which the parameter name can no longer reach once it is bound.
_BACKEND_FIXTURE = backend


@dataclass
class _Captured:
    spec: SessionSpec
    argv: list[str]
    outcome: Outcome


def _spy_write_session(monkeypatch) -> list[_Captured]:
    """`M-c1` (THE capture mechanism) -- patches the PACKAGE-LEVEL
    `self_learn.invocation.write_session` binding, because that is the
    binding `worker._invoke_claude` calls (`spec = invocation.SessionSpec
    (...)` ... `invocation.write_session(spec)`). Patching
    `invocation.registry.write_session` instead (the `BK-a` mirror trap)
    is a SILENT NO-OP: `worker.py` never reads that binding. Records
    `(spec, spec.cli_argv_builder(None), outcome)` -- the spec/argv pair
    `M-c1` names, plus the outcome (the `CH10`-precedent shape) for
    criteria that need the driven verdict."""
    captured: list[_Captured] = []
    real = invocation.write_session

    def spy(spec, **kwargs):
        argv = spec.cli_argv_builder(None)
        outcome = real(spec, **kwargs)
        captured.append(_Captured(spec=spec, argv=argv, outcome=outcome))
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
    argv: list[str] | None = None,
    label: str = "",
) -> SessionSpec:
    if containment is None:
        containment = _worker_containment(home)
    if argv is None:
        settings_path = home / "spec-settings.json"
        if not settings_path.exists():
            settings_path.write_text("{}", encoding="utf-8")
        argv = worker.build_argv(home, settings_path)
    fixed_argv = argv
    return SessionSpec(
        surface=surface,
        prompt=prompt,
        cwd=home,
        timeout=timeout,
        containment=containment,
        log=lambda _msg: None,
        cli_argv_builder=lambda _settings, _a=fixed_argv: _a,
        cli_settings_writer=None,
        label=label,
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


def _make_selective_claude_run(exc: BaseException, real_run=subprocess.run):
    """A `subprocess.run` wrapper that raises `exc` for a `claude`-argv
    call and delegates everything else (`git`, in particular) to the REAL
    function -- `F-c2`'s claude-resolution property applies here too:
    a BLANKET `subprocess.run` replacement is only safe where
    `worker.run()`'s own `git` call in `_digest` is never reached
    (`FL1`/`FL2`, which drive `_invoke_claude` directly, and `HY5`, which
    drives it against a home with no batch to compose); `FL3` drives a
    REAL `worker.run()`, so `os-error` and `not-found` both need the same
    monkeypatch discipline `F-c1` established, scoped to the one argv
    each leg cares about.

    MAJOR-4 (code-gate fold) -- SPEC-DEVIATION NOTE, disclosed here
    rather than left implicit: `F-c`'s table, taken literally, names one
    recipe per (kind, param) cell with no distinction between a direct
    `_invoke_claude` drive and a full `worker.run()` drive. In practice
    the `cli` `not-found`/`os-error` recipe is UNACHIEVABLE for `FL3`
    specifically -- `FL3` drives a real `worker.run()`, whose `_digest`
    step shells out to `git` before any model invocation is reached, so
    a recipe that blanket-replaces `subprocess.run` (or scrubs `claude`
    off PATH entirely) kills the git call too and the leg never reaches
    the code being tested. This selective, argv-matching `subprocess.run`
    patch is the sanctioned form for ALL of `FL1`/`FL2`/`FL3`'s cli
    `not-found`/`os-error` cells -- the mirror of `F-c1`'s own reasoning
    for `HY5` leg 3 (a bare `subprocess.run` replacement is safe there
    ONLY because that leg drives `_invoke_claude` directly, with no `git`
    call in the way). STEP 0's decoy shadow (above) is what now covers
    the sites this recipe's own `not-found`/`os-error` cells leave
    exposed if the argv match itself is ever wrong."""

    def _run(args, *a, **kw):
        if args and args[0] == "claude":
            raise exc
        return real_run(args, *a, **kw)

    return _run


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

    if param == "cli":
        monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
        if kind == "not-found":
            # STEP 0: the decoy is installed FIRST, so if the selective
            # `subprocess.run` patch below ever mis-matches (delegates a
            # `claude`-bound call to the real function instead of
            # raising), PATH resolution still cannot escape the decoy.
            _install_decoy_shadow(scratch, monkeypatch)
            monkeypatch.setattr(
                subprocess, "run",
                _make_selective_claude_run(FileNotFoundError(2, "No such file or directory", "claude")),
            )
            return timeout
        if kind == "os-error":
            _install_decoy_shadow(scratch, monkeypatch)  # STEP 0 backstop
            monkeypatch.setattr(
                subprocess, "run",
                _make_selective_claude_run(OSError("simulated os-error (FL-group)")),
            )
            return timeout
        _build_cli_shim(scratch, monkeypatch)
        if kind == "exit":
            monkeypatch.setenv("CLAUDE_SHIM_EXIT_1", "7")
        elif kind == "timeout":
            timeout = 1.5
            monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "1.5")
            monkeypatch.setenv("CLAUDE_SHIM_SLEEP_1", "5")
        return timeout

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

_ARMOR_SHAS = {
    "plugins/self-learn/cli/tests/conftest.py": "49e0fd2f1c9232d5e9ed6e105e22388aa54bbd53493a7ec7ecc8305ee79224ea",
    "plugins/self-learn/cli/tests/shims.py": "c8f348539263fb71a61026b48f9acac213aa5809b7421c1971ee85639a0f6dcb",
    "plugins/self-learn/cli/tests/backends.py": "a2ba2d74f117a230740d10e3c9fa67bd30f751ce80ec59667c9136557a906dde",
    "plugins/self-learn/cli/tests/test_invocation.py": "e9ee70356d65106848c5857530d43f3bd3ad7244de1a34a4e31aaa200a416c2b",
    "plugins/self-learn/cli/tests/test_invocation_sdk.py": "9a3246318c86eec8b049e655e7ffeee5f370b828134cc9b62a1eef64ced8668a",
    "plugins/self-learn/cli/tests/test_u_fake.py": "72c5010db060a1179a75648ad17a343b8e0bc69e2923f885b3dbe97f3e636a7e",
    "plugins/self-learn/cli/tests/test_worker.py": "39cb1ca0dd6c2dd366c5455da86c875187d884bdee42ac952f558ba3cdbf882a",
    "plugins/self-learn/cli/tests/test_repair.py": "dd0accf9f1315109f93de18adc93d206bea56afc50168a7e1ac7f8d846f91c94",
}

_FAKE_CLAUDE_RELPATH = "plugins/self-learn/cli/tests/fixtures/fake_claude.py"


def test_su4a_whole_file_armor_shas():
    """`SU4` clause (a) -- eight whole-file pins, byte-identical to base.
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
    exists for."""
    for relpath, expected in _ARMOR_SHAS.items():
        working_tree_path = _repo_root() / relpath
        actual = hashlib.sha256(working_tree_path.read_bytes()).hexdigest()
        assert actual == expected, (
            "Shipped armor changed. If this was deliberate, U-sdkw is the "
            f"wrong unit for it -- see §7.5. ({relpath})"
        )
    proc = subprocess.run(
        ["git", "diff", "--stat", BASE_COMMIT, "--", *_ARMOR_SHAS],
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
    # binding hashes the shadow and reddens -- keep this form).
    for name in base_func_names:
        assert name in cur_func_names, f"{name} missing from the current file"
        fn = getattr(fake_claude_mod, name)
        live_src = inspect.getsource(fn)
        assert hashlib.sha256(live_src.encode("utf-8")).hexdigest() == base_shas[name], name

    # leg 2: the new top-level NAME set is exactly the sanctioned pair.
    new_names = cur_func_names - base_func_names
    assert new_names == {"_scenario_ok_write_real", "_next_invocation"}

    # leg 3: SCENARIOS' key set gained exactly one key; every base key
    # survives bound to its ORIGINAL function (by __name__, not presence).
    base_scenarios = base_mod.SCENARIOS
    cur_scenarios = fake_claude_mod.SCENARIOS
    base_keys = set(base_scenarios.keys())
    cur_keys = set(cur_scenarios.keys())
    assert cur_keys - base_keys == {"ok_write_real"}
    assert base_keys <= cur_keys
    for key in base_keys:
        assert base_scenarios[key].__name__ == cur_scenarios[key].__name__, key

    # leg 4: the file's top-level non-FunctionDef statements are exactly
    # base's, save for the SCENARIOS dict literal gaining ONE key --
    # compared as a normalized ast.dump of the statement list (catches
    # the gate's own evasion: an appended module-level rebinding of a
    # pre-existing global, which passes legs 1-3 and the additive
    # numstat).
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
    assert len(base_other) == len(cur_other), (
        "top-level non-FunctionDef statement count changed -- an appended "
        "module-level statement (e.g. a rebound global) is not a "
        "sanctioned SCENARIOS-only delta"
    )
    for b, c in zip(base_other, cur_other):
        assert ast.dump(b) == ast.dump(c)

    base_dict, cur_dict = base_scen_node.value, cur_scen_node.value
    assert isinstance(base_dict, ast.Dict) and isinstance(cur_dict, ast.Dict)
    base_pairs = {ast.dump(k): ast.dump(v) for k, v in zip(base_dict.keys, base_dict.values)}
    cur_pairs = {ast.dump(k): ast.dump(v) for k, v in zip(cur_dict.keys, cur_dict.values)}
    assert set(base_pairs) <= set(cur_pairs)
    for k, v in base_pairs.items():
        assert cur_pairs[k] == v, "a pre-existing SCENARIOS entry changed"
    assert len(set(cur_pairs) - set(base_pairs)) == 1


# ===================================================================== #
# PB -- the parametrized backend harness
# ===================================================================== #


def test_pb1_backend_identity_per_param(backend, tmp_path):
    from self_learn.invocation import CliBackend as _IndependentCliBackend
    from self_learn.invocation_sdk import SdkBackend as _IndependentSdkBackend

    # MAJOR-3 (code-gate fold): PB1's first clause -- the `backend`
    # fixture's OWN declared params, read off its pytest marker, are
    # exactly ("cli", "sdk"). Previously only checked by `FR2` (an
    # instrument criterion that counts collected node ids and does not
    # read assertions, `R-6`) -- a criterion that DIRECTLY reads the
    # fixture's declaration is required so `M2` (params narrowed to
    # `["cli"]` only) reddens `PB1` itself, not only the instrument.
    assert _BACKEND_FIXTURE._fixture_function_marker.params == ("cli", "sdk")

    home = tmp_path / "pb1-home"
    home.mkdir()
    expected = _IndependentCliBackend if backend.param == "cli" else _IndependentSdkBackend
    assert type(invocation.backend_for("worker", home=home)) is expected
    assert type(invocation.backend_for("worker-repair", home=home)) is expected


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


def test_pb4_cli_param_shim_actually_reached(backend, env, monkeypatch):
    if backend.param != "cli":
        pytest.skip("cli-param-only criterion")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid="lrn-000000b4")
    worker.run(env.home)
    assert backend.shim["count"]() >= 1


# ===================================================================== #
# WS -- the write scope and the twin witness
# ===================================================================== #


def test_ws1_batch_containment_and_settings_agree(backend, env, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    captured = _spy_write_session(monkeypatch)
    worker.run(env.home)
    batch_specs = [c for c in captured if c.spec.surface == "worker"]
    assert batch_specs, "no batch invocation captured"
    cap = batch_specs[-1]
    assert cap.spec.containment.write_globs == (f"{worker.stage_dir()}/**",)
    assert cap.spec.containment.write_exact == ()
    settings_path = Path(cap.argv[cap.argv.index("--settings") + 1])
    perms = json.loads(settings_path.read_text(encoding="utf-8"))["permissions"]
    assert invocation.containment_permissions(cap.spec.containment) == perms


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


def test_ws3_cli_witness_b_is_stage_permission_rules(env, claude_cli_shim_worker, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    settings_path = worker.cache_dir() / "worker.settings.json"
    perms = json.loads(settings_path.read_text(encoding="utf-8"))["permissions"]
    expected = worker.stage_permission_rules(env.home)
    assert perms["allow"] == expected
    assert not any("proposals" in rule for rule in perms["allow"])


def test_ws4_stage_disabled_inverts_the_frontier(backend, env, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_STAGE", "0")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    if backend.param == "cli":
        seed_pending(env, rid=_next_rid())
        worker.run(env.home)
        settings_path = worker.cache_dir() / "worker.settings.json"
        perms = json.loads(settings_path.read_text(encoding="utf-8"))["permissions"]
        assert perms["allow"] == worker.write_permission_rules(env.home)
    else:
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


def test_ws5a_stdout_never_parsed_cli_behavioral(env, claude_cli_shim_worker, monkeypatch):
    # MAJOR-2 (code-gate fold): WS5's spec text asserts `Outcome.stdout
    # == ""` on BOTH worker surfaces -- this was previously unimplemented
    # (only `RunResult.status` was checked, which says nothing about
    # what `Outcome.stdout` itself carries). Added via the `M-c1` spy.
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    captured = _spy_write_session(monkeypatch)
    seed_pending(env, rid=_next_rid())
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", "echo 'noise on stdout'")
    result = worker.run(env.home)
    assert result.status == "failed"
    batch_outcome = [c.outcome for c in captured if c.spec.surface == "worker"][-1]
    assert batch_outcome.stdout == ""

    # the repair surface, driven directly (`worker-repair` is the OTHER
    # half of "both worker surfaces").
    captured.clear()
    repair_settings = env.home.parent / "ws5a-repair-settings.json"
    repair_settings.write_text("{}", encoding="utf-8")
    repair_argv = worker.build_argv(env.home, repair_settings)
    worker._invoke_claude(
        repair_argv, "prompt", 20.0, env.home,
        label="repair ", containment=invocation.DEGRADED_WORKER_CONTAINMENT,
    )
    repair_outcome = captured[-1].outcome
    assert repair_outcome.stdout == ""


def test_ws5b_stdout_never_parsed_sdk_behavioral(env, sdk_cli_path, monkeypatch):
    # MAJOR-2: see WS5a.
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
    repair_settings = env.home.parent / "ws5b-repair-settings.json"
    repair_settings.write_text("{}", encoding="utf-8")
    repair_argv = worker.build_argv(env.home, repair_settings)
    worker._invoke_claude(
        repair_argv, "prompt", 20.0, env.home,
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
    src = Path(inspect.getfile(worker)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.Assign):
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            value = node.value
        elif isinstance(node, ast.NamedExpr):
            value = node.value
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Attribute) and func.attr == "write_session":
                pytest.fail(f"worker.py binds the result of write_session at line {node.lineno}")


def test_ws6_attribution_four_cells(backend, env, monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    if backend.param == "cli":
        rid_a = _next_rid()
        seed_pending(env, rid=rid_a)
        monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", shim_writes(env, rid_a))
        result_a = worker.run(env.home)
        installed_a = env.proposals / f"{rid_a}.yaml"
        assert installed_a.is_file()
        assert result_a.proposed == [rid_a]
        assert _installed_matches_written(
            _valid_proposal_yaml(env), installed_a.read_text(encoding="utf-8")
        )

        rid_b = _next_rid()
        seed_pending(env, rid=rid_b)
        outside = tmp_path / "ws6-outside.yaml"
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT_1",
            f"mkdir -p {outside.parent} && cat > {outside} <<'YAML'\nnot a proposal\nYAML",
        )
        result_b = worker.run(env.home)
        assert not (env.proposals / f"{rid_b}.yaml").exists()
        assert list(worker.stage_dir().iterdir()) == []
        assert result_b.status == "failed"
    else:
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
    assert Path(fake.argvs[0][fake.argvs[0].index("--settings") + 1]).name == "worker.settings.json"
    assert Path(fake.argvs[1][fake.argvs[1].index("--settings") + 1]).name == "worker.repair.settings.json"


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
    if backend.param == "cli":
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid))
        )
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid))
        )
    else:
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
    settings_path = home / "worker.repair.settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    repair_argv = worker.build_argv(home, settings_path)

    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    if backend.param == "cli":
        monkeypatch.setenv("CLAUDE_SHIM_EXIT_1", "9")
    else:
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "error_result")

    result = worker._invoke_claude(
        repair_argv, "prompt", worker.repair_timeout_secs(), home,
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
    if backend.param == "cli":
        monkeypatch.setenv("CLAUDE_SHIM_SLEEP_1", "5")
    else:
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
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "1.2")
    home = tmp_path / "to2-home"
    home.mkdir()
    logged: list[str] = []
    monkeypatch.setattr(worker, "log", lambda msg: logged.append(msg))
    settings_path = home / "worker.repair.settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    repair_argv = worker.build_argv(home, settings_path)
    if backend.param == "cli":
        monkeypatch.setenv("CLAUDE_SHIM_SLEEP_1", "5")
    else:
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")

    start = time.monotonic()
    with _Watchdog(1.2 * 8):  # BLOCKER-2 -- interrupts, does not just measure
        result = worker._invoke_claude(
            repair_argv, "prompt", worker.repair_timeout_secs(), home,
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
    if backend.param == "cli":
        monkeypatch.setenv("CLAUDE_SHIM_SLEEP_1", "5")
    else:
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
            settings_path = home / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            argv = worker.build_argv(home, settings_path)
            containment = _worker_containment(home)
            if kind == "os-error" and backend.param == "sdk":
                containment = dataclasses.replace(containment, write_globs=("/tmp/[bad/**",))
            with _Watchdog(timeout * 8):  # MAJOR-A (code-gate fold) -- bounds the sdk/timeout cell (M31), same as TO's BLOCKER-2
                result = worker._invoke_claude(
                    argv, "PROMPT", timeout, home, label="", containment=containment
                )
            assert result is None
            assert captured, f"no session recorded for kind={kind}"
            observed = captured[-1].outcome.failure
            assert observed == kind, (kind, observed)
            driven.add(observed)
        finally:
            mp.undo()
    assert driven == set(invocation.FAILURE_KINDS)  # F-b -- the fail-closed enumeration, per backend


def _drive_fl2_lines(param: str, tmp_path: Path, marker_templates) -> dict[str, list[str]]:
    """One param's worth of `F-c` table cells, log lines captured under
    the marker-tagged templates. Factored out so `FL2` can drive a SECOND
    param from inside a single-param test body (below) without duplicating
    the drive loop -- the cross-backend byte-identity clause needs both
    sides' lines in the same assertion."""
    results: dict[str, list[str]] = {}
    for kind in invocation.FAILURE_KINDS:
        mp = pytest.MonkeyPatch()
        try:
            home = tmp_path / f"fl2-{param}-{kind}"
            home.mkdir()
            logged: list[str] = []
            mp.setattr(worker, "log", lambda msg, _l=logged: _l.append(msg))
            mp.setitem(invocation.LOG_TEMPLATES, "worker", marker_templates)

            timeout = _apply_failure_env(kind, param, scratch=home, monkeypatch=mp)
            settings_path = home / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            argv = worker.build_argv(home, settings_path)
            containment = _worker_containment(home)
            if kind == "os-error" and param == "sdk":
                containment = dataclasses.replace(containment, write_globs=("/tmp/[bad/**",))

            with _Watchdog(timeout * 8):  # MAJOR-A (code-gate fold) -- bounds the sdk/timeout cell (M31), same as TO's BLOCKER-2
                worker._invoke_claude(argv, "PROMPT", timeout, home, label="", containment=containment)
            results[kind] = list(logged)
        finally:
            mp.undo()
    return results


def test_fl2_byte_identity_and_provenance(tmp_path, backend):
    # `FL-c`/`FR2`: declared `(T2 + T3)`, so parametrized over `backend`
    # rather than an internal double loop. The provenance-and-shape clause
    # is naturally per-param; the byte-identity clause needs BOTH sides,
    # so it rides the `sdk` param leg, which additionally drives a fresh
    # `cli` pass via `_drive_fl2_lines` to compare against -- `R-6`
    # explicitly permits a criterion's two param legs to carry asymmetric
    # weight, since `FR2` counts node ids rather than reading assertions.
    original = invocation.LOG_TEMPLATES["worker"]
    marker_templates = dataclasses.replace(
        original,
        exited=f"MARKER-EXITED {original.exited}",
        timed_out=f"MARKER-TIMEOUT {original.timed_out}",
        not_found=f"MARKER-NOTFOUND {original.not_found}",
        os_error=f"MARKER-OSERROR {original.os_error}",
        unavailable=f"MARKER-UNAVAIL {original.unavailable}",
    )

    own = _drive_fl2_lines(backend.param, tmp_path, marker_templates)

    # provenance and shape, for all five (the os-error/sdk cell is the
    # documented exception -- R-10, silent by construction).
    for kind in invocation.FAILURE_KINDS:
        lines = own[kind]
        if kind == "os-error" and backend.param == "sdk":
            assert lines == [], lines
            continue
        assert lines, (backend.param, kind)
        assert any("MARKER-" in l for l in lines), (backend.param, kind, lines)

    # exit: shape only -- rc is fixture-determined on cli, synthesized on sdk.
    exit_line = own["exit"][0]
    if backend.param == "cli":
        assert re.match(r"^MARKER-EXITED run: claude exited 7: ", exit_line), exit_line
    else:
        assert re.match(r"^MARKER-EXITED run: claude exited 1: ", exit_line), exit_line

    if backend.param == "sdk":
        # byte-identity, scoped to timeout (first line) / not-found / unavailable.
        other = _drive_fl2_lines("cli", tmp_path, marker_templates)
        for kind in ("timeout", "not-found", "unavailable"):
            cli_line = other[kind][0]
            sdk_line = own[kind][0]
            assert cli_line == sdk_line, (kind, cli_line, sdk_line)


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


def test_ha1_cli_hatch_open_omits_default_mode(env, claude_cli_shim_worker, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")
    rid = _next_rid()
    seed_pending(env, rid=rid)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_1", _defect_script(env, rid, _t4_missing_target(env, rid)))
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT_2", _defect_script(env, rid, _t4_target_fixed(env, rid)))
    captured = _spy_write_session(monkeypatch)
    worker.run(env.home)
    specs = [c.spec for c in captured]
    batch_spec = next(s for s in specs if s.surface == "worker")
    repair_spec = next(s for s in specs if s.surface == "worker-repair")
    assert batch_spec.containment.default_mode is None
    assert repair_spec.containment.default_mode is None
    settings = json.loads((worker.cache_dir() / "worker.settings.json").read_text(encoding="utf-8"))["permissions"]
    repair_settings = json.loads(
        (worker.cache_dir() / "worker.repair.settings.json").read_text(encoding="utf-8")
    )["permissions"]
    assert "defaultMode" not in settings
    assert "defaultMode" not in repair_settings


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
    # (replacing direct `claude_cli_shim_worker`/`sdk_cli_path` fixture
    # use -- `backend`'s own branches already build the same shim/sdk env,
    # `SU5`'s census updated accordingly). Leg (i) splits by param: the
    # `cli` leg checks the settings-file half, the `sdk` leg checks the
    # denial half -- both are "the variable unset" case the spec's leg (i)
    # names, just observed through each backend's own witness.
    if backend.param == "cli":
        seed_pending(env, rid=_next_rid())
        monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
        worker.run(env.home)
        settings = json.loads((worker.cache_dir() / "worker.settings.json").read_text(encoding="utf-8"))["permissions"]
        assert settings.get("defaultMode") == "default"
    else:
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
    if backend.param == "cli":
        # NOTE (code-gate fold): HA4's cli half also claims the ARGV is
        # byte-identical with and without the variable -- previously only
        # the settings-file `allow` list was checked. Captured via the
        # `M-c1` spy alongside the existing settings-file comparison.
        captured = _spy_write_session(monkeypatch)
        results = {}
        argvs = {}
        for scope in ("1", "0"):
            monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", scope)
            logged.clear()
            captured.clear()
            seed_pending(env, rid=_next_rid())
            worker.run(env.home)
            settings = json.loads(
                (worker.cache_dir() / "worker.settings.json").read_text(encoding="utf-8")
            )["permissions"]
            results[scope] = settings
            argvs[scope] = [c.argv for c in captured if c.spec.surface == "worker"][-1]
            hatch_lines = [
                l for l in logged
                if "enforce" in l.lower() or "hatch" in l.lower() or "ENFORCE_SCOPE" in l
            ]
            assert hatch_lines == []
        assert results["1"]["allow"] == results["0"]["allow"]
        assert results["1"].get("defaultMode") == "default"
        assert "defaultMode" not in results["0"]
        assert argvs["1"] == argvs["0"]
    else:
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


def _bg_argv(home: Path) -> list[str]:
    settings_path = home / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    return worker.build_argv(home, settings_path)


def test_bg1_prompt_not_in_argv(backend, tmp_path, monkeypatch):
    # BLOCKER-1 (code-gate fold): re-routed through `worker._invoke_claude`
    # -- the hand-built `_spec_for`/`write_session` drive never exercised
    # the worker's OWN prompt handling, so a mutation truncating the
    # prompt INSIDE `_invoke_claude` (`M12`) was invisible to this group.
    assert len(BIG_PROMPT.encode("utf-8")) > 128 * 1024
    home = tmp_path / "bg1-home"
    home.mkdir()
    captured = _spy_write_session(monkeypatch)
    argv = _bg_argv(home)
    containment = _worker_containment(home)
    worker._invoke_claude(argv, BIG_PROMPT, 20.0, home, label="", containment=containment)
    cap = captured[-1]
    assert BIG_PROMPT not in cap.argv
    assert all(len(a.encode("utf-8")) <= 128 * 1024 for a in cap.argv)
    if backend.param == "sdk":
        kwargs = backend_mod.options_kwargs(cap.spec)
        assert BIG_PROMPT not in str(kwargs.get("system_prompt"))


def test_bg2_cli_prompt_delivered_intact_on_stdin(claude_cli_shim_worker, tmp_path, monkeypatch):
    # BLOCKER-1: routed through `worker._invoke_claude` (see BG1).
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    home = tmp_path / "bg2-home"
    home.mkdir()
    argv = _bg_argv(home)
    containment = _worker_containment(home)
    worker._invoke_claude(argv, BIG_PROMPT, 20.0, home, label="", containment=containment)
    delivered = claude_cli_shim_worker["call_prompt"](1)
    assert delivered == BIG_PROMPT


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

    argv = _bg_argv(home)
    containment = _worker_containment(home)
    worker._invoke_claude(argv, BIG_PROMPT, 20.0, home, label="", containment=containment)
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


def test_ev4_tool_events_string_confined_to_events_module():
    src_root = Path(inspect.getfile(worker)).parent
    hits = []
    for path in sorted(src_root.rglob("*.py")):
        if "tool-events" in path.read_text(encoding="utf-8"):
            hits.append(path)
    assert hits, "no occurrence of 'tool-events' found anywhere -- EV4 has nothing to pin"
    allowed = src_root / "invocation_sdk" / "events.py"
    for path in hits:
        assert path == allowed, f"'tool-events' substring found outside {allowed}: {path}"


def test_ev5_cli_leaves_no_events_file(env, claude_cli_shim_worker, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")
    seed_pending(env, rid=_next_rid())
    worker.run(env.home)
    assert _worker_events_files() == []


# ===================================================================== #
# FR -- flip readiness, not flip
# ===================================================================== #


def test_fr1_backend_worker_sdk_resolves_both_surfaces(tmp_path, monkeypatch, sdk_cli_path):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    from self_learn.invocation_sdk import SdkBackend as _IndependentSdkBackend

    home = tmp_path / "fr1-home"
    home.mkdir()
    b1 = invocation.backend_for("worker", home=home)
    b2 = invocation.backend_for("worker-repair", home=home)
    assert type(b1) is _IndependentSdkBackend
    assert type(b2) is _IndependentSdkBackend


def test_fr3_default_stays_cli(tmp_path, monkeypatch):
    for var in ("SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER", "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "fr3-home"
    home.mkdir()
    from self_learn.invocation import CliBackend as _IndependentCliBackend

    b1 = invocation.backend_for("worker", home=home)
    b2 = invocation.backend_for("worker-repair", home=home)
    assert type(b1) is _IndependentCliBackend
    assert type(b2) is _IndependentCliBackend
    assert invocation.KNOWN_BACKENDS == ("cli", "sdk")
    # instrument half: `git diff 89f8ef7..HEAD -- .../registry.py` empty
    # -- recorded in the build report, not asserted here (`FL-b`).


def test_fr4_selector_mapping_does_not_cross_govern(tmp_path, monkeypatch):
    home = tmp_path / "fr4-home"
    home.mkdir()
    for var in ("SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER", "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST"):
        monkeypatch.delenv(var, raising=False)

    from self_learn.invocation import CliBackend as _IndependentCliBackend

    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "sdk")
    assert type(invocation.backend_for("worker", home=home)) is _IndependentCliBackend
    assert type(invocation.backend_for("worker-repair", home=home)) is _IndependentCliBackend
    monkeypatch.delenv("SELF_LEARN_BACKEND_MINER")
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST")

    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    assert type(invocation.backend_for("miner-reader", home=home)) is _IndependentCliBackend
    assert type(invocation.backend_for("analyst", home=home)) is _IndependentCliBackend


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


def test_hy5_cli_side_no_real_claude_control(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    home = tmp_path / "hy5-home"
    home.mkdir()
    shim = _build_cli_shim(tmp_path, monkeypatch)

    # legs 1 + 2: exclusive AND exhaustive claude-resolution.
    resolved = shutil.which("claude")
    assert resolved is not None
    resolved_path = Path(resolved).resolve()
    assert str(resolved_path).startswith(str(tmp_path.resolve())), resolved_path  # leg 1
    assert resolved_path == (shim["dir"] / "claude").resolve()  # leg 2

    # leg 3: the os-error recipe reaches the monkeypatch, not a process.
    calls: list[tuple] = []
    real_run = subprocess.run

    def _counting_os_error_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("simulated os-error (HY5 leg 3)")

    monkeypatch.setattr(subprocess, "run", _counting_os_error_run)
    settings_path = home / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    argv = worker.build_argv(home, settings_path)
    containment = _worker_containment(home)
    result = worker._invoke_claude(argv, "PROMPT", 20.0, home, label="", containment=containment)
    assert result is None
    assert shim["count"]() == 0
    assert len(calls) == 1
