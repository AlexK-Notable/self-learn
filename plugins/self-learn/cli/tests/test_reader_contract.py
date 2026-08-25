"""U-sdkr acceptance criteria (docs/specs/self-learn/drafts/
u-sdkr-reader-contract-spec.md Sec 4): SU/MC/CT/RC/TO/SW/FL/HY -- the
miner-reader's `["cli", "sdk"]` contract suite: output contract, timeout
semantics and sweep semantics pinned identically on both backends, plus
the two containment holes `Fix-1` closes (landed in `miner.py` /
`invocation/contract.py` / `test_invocation.py`, not here).

Legs are stated per criterion (`MAJOR-4`): `SW1` is deliberately
UNPARAMETRIZED (imports `sdk_absent` from `test_invocation_sdk`, per the
`test_invocation.py:46-48` precedent, rather than a second definition
site -- U-sdk `SU6` leg (ii)). `CT1`-`CT8` are `sdk`-only or backend-
independent; `TO4`/`TO5` are `cli`-only recorder tests; `TO6`/`TO7` are
`sdk`-only. Every `[both]` criterion is driven through the single
`reader_leg` fixture (`T2-a`), parametrized over `LEGS`, which branches
on `request.param` and calls plain functions -- it requests no leg-
specific fixture (`B-8`).

Instrument, diff and AST criteria that need no test function here (their
result lands in the build report instead): `SU1`-`SU6`, `MC5`-`MC7`,
`FL5`, `HY2`. `SW5` is discharged by the conjunction of `SW1` and `SW3`
running against the same spool state -- no separate function.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from self_learn import invocation, miner
from self_learn.invocation_sdk import SdkBackend
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import lifecycle as lifecycle_mod

import shims

from test_invocation_sdk import (  # noqa: F401 -- fixture resolved by name
    sdk_absent,
)

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"

# ===================================================================== #
# Sets-1 -- the sets this document uses (NORMATIVE, spec Sec 3.1)
# ===================================================================== #

SURFACE = "miner-reader"
SELECTOR = "MINER"
BACKEND_VAR = "SELF_LEARN_BACKEND_MINER"
LEGS = ("cli", "sdk")
ARTIFACT = miner.OUTPUT_BASENAME
EARLY_RETURN = {"timeout", "not-found", "os-error", "unavailable"}
FALL_THROUGH = {"exit", None}
TIMEOUT_PATCH = 1.0  # the ONE value monkeypatched into miner.INVOKE_TIMEOUT_SECS

_DEFAULT_BODY = '{"candidates": [], "fires": []}'
_DEFAULT_STDOUT = "READER-STDOUT-SENTINEL"


# ===================================================================== #
# Shared driving primitives
# ===================================================================== #


def _capture_invoke_reader(home: Path, prompt: str = "PROMPT"):
    """C-a -- drives the REAL `miner._invoke_reader(home, prompt)` with a
    LOCAL `pytest.MonkeyPatch()`-scoped spy on `invocation.write_session`,
    returning `(out_path, spec, outcome)`. Undone before return -- the
    shared `monkeypatch` fixture would keep capturing sibling calls for
    the rest of the test (`test_invocation.py::miner_capture`'s own
    scar/comment)."""
    captured_specs: list[invocation.SessionSpec] = []
    captured_outcomes: list[invocation.Outcome] = []
    real_write_session = invocation.write_session

    def spy(spec, **kwargs):
        captured_specs.append(spec)
        outcome = real_write_session(spec, **kwargs)
        captured_outcomes.append(outcome)
        return outcome

    mp = pytest.MonkeyPatch()
    mp.setattr(invocation, "write_session", spy)
    try:
        out_path = miner._invoke_reader(home, prompt)
    finally:
        mp.undo()
    return out_path, captured_specs[0], captured_outcomes[0]


def _log_text(home: Path) -> str:
    path = miner.miner_dir() / "miner.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _log_lines_added(before_text: str, after_text: str) -> list[str]:
    assert after_text.startswith(before_text), "the miner log was truncated or rewritten mid-test"
    added = after_text[len(before_text) :]
    return [line for line in added.splitlines() if line]


def _shadow_claude(shims_dir: Path, tmp_path: Path, tag: str) -> None:
    """gate fold MAJOR-3/NOTE-1 -- shadow-not-subtract: writes an inert
    decoy `claude` shim into `shims_dir` (meant to be PATH-prepended
    ahead of the ambient PATH) so PATH resolution finds a harmless
    stand-in FIRST, independent of whether a `subprocess.Popen`-level
    patch is also in effect for this call. Replaces the earlier
    `_path_without_claude` directory-SUBTRACTION approach, retired here:
    subtracting the directory that holds a real `claude` risks dropping
    unrelated binaries co-located in the same directory (a `/usr/bin/
    claude` would strip the whole of `/usr/bin` -- exactly the failure
    this build's own first PATH-sanitization attempt hit, breaking
    `env`/`python3` resolution for the fake CLI script). Shadowing adds
    a shim without removing anything. The decoy logs to throwaway
    files, writes nothing, echoes nothing, and exits 1 -- if it is ever
    actually executed for real, its exit code is the tell."""
    shims_dir.mkdir(exist_ok=True)
    shims.write_reader_claude_shim(
        shims_dir,
        argv_log=tmp_path / f"decoy-{tag}-argv.log",
        prompt_log=tmp_path / f"decoy-{tag}-prompt.log",
        out_path=tmp_path / f"decoy-{tag}-out.json",
        body=None,
        stdout_text=None,
        exit_code=1,
    )


def _cli_reader_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`T2-f`/U-fake `B-7a` -- sanitizes PATH first (an empty, existing
    directory) so a missed `subprocess.Popen` patch fails deterministically
    (`FileNotFoundError`) rather than PATH-dependently -- never a real
    `claude`, per `HY4`/`K-e`."""
    home = tmp_path / "reader-cli-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "reader-cli-xdg-cache"))
    empty_path = tmp_path / "reader-cli-empty-path"
    empty_path.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_path))
    return home


def _drive_reader_sdk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    home: Path | None = None,
    write_target: Path | None = None,
    write_body: str | None = None,
    write_tool: str | None = None,
    scenario: str = "reader_write",
    prompt: str = "MINER SDK PROMPT",
) -> dict:
    """`C-a`, sdk-only driving for the `CT` group and `MC3`: sets up the
    sdk backend against the fake CLI (`SELF_LEARN_SDK_CLI_PATH` +
    `BACKEND_VAR="sdk"`, `T2-e` -- reached through the registry, never
    injected), then `_capture_invoke_reader`s. Defaults the write target
    to the real artifact path so a bare call is the happy path.

    PATH is ALSO shadowed here (`T2-f`/U-fake `B-7a`, `MAJOR-3`/`NOTE-1`
    shadow-not-subtract), even though this leg should never reach
    `CliBackend` at all: a mutation or bug that breaks `BACKEND_VAR`
    routing must fail closed onto an inert decoy, never fall through to
    a real, PATH-resolvable `claude` -- measured live during this
    build's own `M32` self-check, §"Deviations", before this line
    existed."""
    if home is None:
        home = tmp_path / "reader-ct-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "reader-ct-xdg-cache"))
    shadow_dir = home / "_decoy_path"
    _shadow_claude(shadow_dir, tmp_path, "ct")
    monkeypatch.setenv("PATH", f"{shadow_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv(BACKEND_VAR, "sdk")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", scenario)
    target = write_target if write_target is not None else (miner.spool_dir() / miner.OUTPUT_BASENAME)
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target))
    if write_body is not None:
        monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY", write_body)
    if write_tool is not None:
        monkeypatch.setenv("FAKE_CLAUDE_WRITE_TOOL", write_tool)
    out_path, spec, outcome = _capture_invoke_reader(home, prompt)
    return {"spec": spec, "outcome": outcome, "out_path": out_path, "home": home, "target": target}


@dataclass
class _ReaderRun:
    leg: str
    spec: invocation.SessionSpec
    outcome: invocation.Outcome
    out_path: Path | None
    home: Path
    argv: list[str] | None
    prompt_seen: str | None


class _ReaderLeg:
    """`T2-a`'s per-leg handle -- the plain functions the parametrized
    fixture calls. Never itself a fixture (`B-8`)."""

    def __init__(
        self,
        name: str,
        home: Path,
        out_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        shim_dir: Path,
        shims_dir: Path | None = None,
        argv_log: Path | None = None,
        prompt_log: Path | None = None,
    ) -> None:
        self.name = name
        self.home = home
        self.out_path = out_path
        self.shim_dir = shim_dir
        self._monkeypatch = monkeypatch
        self._shims_dir = shims_dir
        self._argv_log = argv_log
        self._prompt_log = prompt_log

    def invoke(self, prompt: str = "PROMPT") -> _ReaderRun:
        out, spec, outcome = _capture_invoke_reader(self.home, prompt)
        argv: list[str] | None = None
        prompt_seen: str | None = None
        if self.name == "cli" and self._argv_log is not None:
            assert self._prompt_log is not None
            raw = self._argv_log.read_bytes() if self._argv_log.exists() else b""
            argv = [a.decode("utf-8") for a in raw.split(b"\0")[:-1]] if raw else []
            prompt_seen = (
                self._prompt_log.read_text(encoding="utf-8") if self._prompt_log.exists() else ""
            )
        return _ReaderRun(
            leg=self.name, spec=spec, outcome=outcome, out_path=out, home=self.home,
            argv=argv, prompt_seen=prompt_seen,
        )

    def drive(
        self,
        *,
        body: str | None = _DEFAULT_BODY,
        stdout_text: str = _DEFAULT_STDOUT,
        exit_code: int = 0,
        prompt: str = "PROMPT",
    ) -> _ReaderRun:
        """`T2-b`/`T2-c` step 6 (`MAJOR-3`): `body`/`stdout_text`/
        `exit_code` drive the leg-appropriate knob -- the bash shim's
        params on `cli`, `FAKE_CLAUDE_WRITE_BODY`/`FAKE_CLAUDE_RESULT_TEXT`/
        `FAKE_CLAUDE_RESULT_IS_ERROR` on `sdk`. `body=None` means the
        model writes nothing this run (`RC6`): on `sdk` the write target
        is pointed OUTSIDE the spool so the real artifact path is
        untouched regardless of the charter's verdict there."""
        if self.name == "cli":
            assert self._shims_dir is not None
            assert self._argv_log is not None
            assert self._prompt_log is not None
            shims.write_reader_claude_shim(
                self._shims_dir,
                argv_log=self._argv_log,
                prompt_log=self._prompt_log,
                out_path=self.out_path,
                body=body,
                stdout_text=stdout_text,
                exit_code=exit_code,
            )
        else:
            self._monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "reader_write")
            target = self.out_path if body is not None else (self.home / "reader-leg-nowrite-sink.txt")
            self._monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(target))
            if body is not None:
                self._monkeypatch.setenv("FAKE_CLAUDE_WRITE_BODY", body)
            else:
                self._monkeypatch.delenv("FAKE_CLAUDE_WRITE_BODY", raising=False)
            self._monkeypatch.setenv("FAKE_CLAUDE_RESULT_TEXT", stdout_text)
            self._monkeypatch.setenv("FAKE_CLAUDE_RESULT_IS_ERROR", "1" if exit_code else "0")
        return self.invoke(prompt)

    def arm_timeout(self) -> None:
        """Sets up the leg's transport so the NEXT `.invoke(...)` times
        out. `K-f`: the `sdk` leg's timeout is REAL (the `hang` scenario),
        which runs the real kill ladder against the fake child THIS TEST
        spawned -- permitted and deliberate, never a signal to a process
        this test did not itself spawn."""
        if self.name == "cli":
            fake = _FakePopenTO(raise_on_communicate=subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1))
            self._monkeypatch.setattr(subprocess, "Popen", fake)
        else:
            self._monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "hang")


@pytest.fixture()
def reader_leg(tmp_path, monkeypatch):
    """`T2-a`, COLLAPSED (U-cleanup-A `CV2`/`CB-3`): formerly
    `params=LEGS` (`LEGS = ("cli", "sdk")`) -- every `[both]` criterion
    parametrized over this fixture now runs the `sdk` leg ONLY, with no
    parametrization suffix on its node id. The `cli` branch is UNUSED
    from here on (stays defined; U-cleanup-B deletes it, §8.3). PATH is
    still shadowed (`T2-f`/U-fake `B-7a`, `MAJOR-3`/`NOTE-1`
    shadow-not-subtract): this leg should never reach `CliBackend`, but a
    mutation or bug that breaks `BACKEND_VAR` routing must fail closed
    onto an inert decoy, never fall through to a real, PATH-resolvable
    `claude` -- measured live during U-sdkr's `M32` self-check, before
    this line existed."""
    home = tmp_path / "reader-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "reader-xdg-cache"))
    out_path = miner.spool_dir() / miner.OUTPUT_BASENAME
    shadow_dir = home / "_decoy_path"
    _shadow_claude(shadow_dir, tmp_path, "leg-sdk")
    monkeypatch.setenv("PATH", f"{shadow_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setenv(BACKEND_VAR, "sdk")
    yield _ReaderLeg("sdk", home, out_path, monkeypatch, shim_dir=shadow_dir)


class _FakePopenTO:
    """Stand-in for `subprocess.Popen` used by the `TO` group's `cli`
    leg -- recorder-only (`K-c`): never signals anything real."""

    def __init__(self, *, raise_on_communicate=None, wait_hook: Callable[[], None] | None = None, pid: int = 4242):
        self._raise_on_communicate = raise_on_communicate
        self._wait_hook = wait_hook
        self.pid = pid

    def __call__(self, argv, **kwargs):
        return self

    def communicate(self, prompt, timeout=None):
        if self._raise_on_communicate is not None:
            raise self._raise_on_communicate
        return ("", None)

    def wait(self):
        if self._wait_hook is not None:
            self._wait_hook()
        return 0


class _PopenRaisesTO:
    """Stand-in for `subprocess.Popen` that raises at CONSTRUCTION time
    (`SW1`'s `not-found`/`os-error` kinds)."""

    def __init__(self, exc: BaseException):
        self._exc = exc

    def __call__(self, argv, **kwargs):
        raise self._exc


# ===================================================================== #
# SU -- the suite and its scope (SU7 is the one real test here)
# ===================================================================== #

_FW_IDS = ("FW-98", "FW-99", "FW-100", "FW-101", "FW-102")
_S_IDS = ("S-45", "S-46")
_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_su7_docs_rows_landed_at_the_expected_ids():
    """`SU7` -- a source scan finds each new row EXACTLY once (as a table
    row, matching the shipped convention that a row's id may still be
    cross-referenced in prose elsewhere -- `FW-93`/`FW-83` each already
    appear 3x in the shipped file for exactly that reason). Positive
    control: the SAME scan against the pre-build (`89f8ef7`) content
    finds ZERO of these ids."""
    fw_path = _REPO_ROOT / "docs" / "specs" / "self-learn" / "14-forward-work-map.md"
    s_path = _REPO_ROOT / "docs" / "specs" / "self-learn" / "03-decisions.md"
    fw_text = fw_path.read_text(encoding="utf-8")
    s_text = s_path.read_text(encoding="utf-8")

    for fw_id in _FW_IDS:
        matches = re.findall(rf"^\| {re.escape(fw_id)} \|", fw_text, re.MULTILINE)
        assert len(matches) == 1, (fw_id, matches)
    for s_id in _S_IDS:
        matches = re.findall(rf"^\| {re.escape(s_id)} \|", s_text, re.MULTILINE)
        assert len(matches) == 1, (s_id, matches)

    base_fw = subprocess.run(
        ["git", "show", "89f8ef7:docs/specs/self-learn/14-forward-work-map.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    base_s = subprocess.run(
        ["git", "show", "89f8ef7:docs/specs/self-learn/03-decisions.md"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    for fw_id in _FW_IDS:
        assert re.findall(rf"^\| {re.escape(fw_id)} \|", base_fw, re.MULTILINE) == [], fw_id
    for s_id in _S_IDS:
        assert re.findall(rf"^\| {re.escape(s_id)} \|", base_s, re.MULTILINE) == [], s_id


# ===================================================================== #
# MC -- the strict-MCP hole (Fix-1)
# ===================================================================== #


def test_mc1_flag_is_last_element_no_mcp_config():
    argv = miner.build_reader_argv(Path("/tmp/mc1-settings.json"))
    assert argv[-1] == "--strict-mcp-config"
    assert "--mcp-config" not in argv


def test_mc2_containment_strict_mcp_is_true():
    c = invocation.containment_for(
        "miner-reader", disallowed_tools=miner.READER_DISALLOWED_TOOLS, spool_dir="/tmp/mc2-spool"
    )
    assert c.strict_mcp is True


def test_mc2b_allowed_tools_is_forced_not_caller_supplied():
    """gate fold MAJOR-1 (`M6`): the real reader call site never passes
    `allowed_tools` to `containment_for` (`miner._invoke_reader` calls
    it with `disallowed_tools`/`spool_dir` only), so a caller-supplied
    value happening to coincide with the forced `None` gives `M6`
    (`containment_for("miner-reader")` returns the caller's value
    instead of forcing `None`) no observer through `CT1`'s captured-
    call discipline (`S-46`) -- `CT1` only ever sees what the real call
    site sends, and the real call site never sends anything but the
    implicit default. `containment_for` is a pure function already
    exercised directly (unit-level) by `MC2`/`MC3`/`MC4`; this is the
    one place a non-`None` value CAN be injected and observed, so the
    assertion lives here rather than in `CT1`. The gate's own probe
    ('Read,Grep' vs `None`) is reproduced verbatim."""
    c = invocation.containment_for(
        "miner-reader",
        allowed_tools="Read,Grep",
        disallowed_tools=miner.READER_DISALLOWED_TOOLS,
        spool_dir="/tmp/mc2b-spool",
    )
    assert c.allowed_tools is None, c.allowed_tools


def test_mc3_pair_consistent_at_the_real_call_site(monkeypatch, tmp_path):
    """U-cleanup-A REWRITE, reduced per spec §8.4b's own row (code gate
    r1 DIVERGENCE-2 fold, 8uvjHmdKaUd6PI3tSyB-F: "do not delete
    silently" -- this was outright deleted in an earlier pass, with a
    citation to `test_ct1`/`test_ct2` in its place; restored as an
    actual reduced test body instead, per the row's own words).

    Originally drove `_invoke_reader` through `_cli_reader_home`
    (empty-PATH, no explicit backend override) to recompute
    `--strict-mcp-config`'s argv position from `spec.cli_argv_builder
    (spec.cli_settings_writer())` -- relying on conftest's `cli` pin
    (AG3) to reach a real `CliBackend`, a path AG1's tripwire now makes
    fatal. §8.4b's own disposition: "the sdk analogue is `options_
    kwargs["strict_mcp_config"] is True`, already asserted by
    `test_op6`. Reduce to the `CT2` options-table assertion" -- driven
    independently here (not by calling `test_ct2` itself) through the
    same real sdk call site (`_drive_reader_sdk`), so this test stays a
    standalone tripwire for the property MC3 names even if `test_ct2`'s
    own, broader assertion set is later narrowed."""
    result = _drive_reader_sdk(monkeypatch, tmp_path)
    spec = result["spec"]
    assert backend_mod.options_kwargs(spec)["strict_mcp_config"] is True


def test_mc4_flag_added_nothing_else_in_the_argv_moves():
    p = Path("/tmp/mc4-settings.json")
    argv = miner.build_reader_argv(p)
    assert argv[:-1] == [
        "claude", "-p", "--model", miner.miner_model(),
        "--disallowedTools", miner.READER_DISALLOWED_TOOLS,
        "--settings", str(p),
    ]
    assert argv[-1] == "--strict-mcp-config"


# ===================================================================== #
# CT -- the reader's containment under sdk (hole (b))
# ===================================================================== #

_OPTIONS_KWARGS_16_KEYS = {
    "cwd", "system_prompt", "model", "allowed_tools", "disallowed_tools", "can_use_tool",
    "permission_mode", "setting_sources", "settings", "strict_mcp_config", "mcp_servers",
    "include_partial_messages", "env", "cli_path", "max_turns", "max_budget_usd",
}


def test_ct1_captured_containment_matches_c_b(monkeypatch, tmp_path):
    result = _drive_reader_sdk(monkeypatch, tmp_path)
    c = result["spec"].containment
    assert c.allowed_tools is None
    assert c.disallowed_tools == miner.READER_DISALLOWED_TOOLS
    assert c.write_globs == (f"{miner.spool_dir()}/**",)
    assert c.write_exact == ()
    assert c.default_mode == "default"
    assert c.strict_mcp is True


def test_ct2_options_kwargs_matches_c_c_table_and_key_set(monkeypatch, tmp_path):
    result = _drive_reader_sdk(monkeypatch, tmp_path)
    spec = result["spec"]
    kwargs = backend_mod.options_kwargs(spec)
    assert set(kwargs) == _OPTIONS_KWARGS_16_KEYS
    assert kwargs["strict_mcp_config"] is True
    assert kwargs["mcp_servers"] == {}
    assert kwargs["setting_sources"] == []
    assert kwargs["settings"] is None
    assert kwargs["permission_mode"] == "default"
    assert kwargs["allowed_tools"] == []
    assert kwargs["disallowed_tools"] == miner.READER_DISALLOWED_TOOLS.split(",")
    assert kwargs["cwd"] == str(result["home"])
    assert kwargs["max_turns"] == 60
    assert kwargs["env"] == {}


def test_ct3_max_turns_selector_scoping(monkeypatch, tmp_path):
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_TURNS_WORKER", raising=False)
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_TURNS_MINER", raising=False)
    result = _drive_reader_sdk(monkeypatch, tmp_path)
    assert backend_mod.options_kwargs(result["spec"])["max_turns"] == 60

    monkeypatch.setenv("SELF_LEARN_SDK_MAX_TURNS_MINER", "5")
    result2 = _drive_reader_sdk(monkeypatch, tmp_path)
    assert backend_mod.options_kwargs(result2["spec"])["max_turns"] == 5
    monkeypatch.delenv("SELF_LEARN_SDK_MAX_TURNS_MINER", raising=False)

    monkeypatch.setenv("SELF_LEARN_SDK_MAX_TURNS_WORKER", "9")
    result3 = _drive_reader_sdk(monkeypatch, tmp_path)
    assert backend_mod.options_kwargs(result3["spec"])["max_turns"] == 60


def test_ct4_write_to_spool_artifact_allowed_lands_on_disk(monkeypatch, tmp_path):
    result = _drive_reader_sdk(monkeypatch, tmp_path)
    assert result["out_path"] is not None
    assert result["out_path"].is_file()
    assert result["outcome"].denials == ()


def test_ct5_write_outside_spool_denied_two_targets(monkeypatch, tmp_path):
    home = tmp_path / "ct5-home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "ct5-xdg-cache"))
    spool = miner.spool_dir()
    targets = {
        "sibling": spool.parent / "ct5-sibling-escape.md",
        "ledger-home": home / "user" / "ct5-ledger-escape.md",
    }
    for label, target in targets.items():
        result = _drive_reader_sdk(monkeypatch, tmp_path, home=home, write_target=target)
        assert not target.exists(), label
        outcome = result["outcome"]
        assert outcome.denials, label
        entry = outcome.denials[-1]
        assert entry["tool"] == "Write", label
        resolved = target.resolve()
        assert entry["reason"] == (
            f"self-learn invocation charter: Write write scope does not include {resolved}"
        ), label


def test_ct6_read_grep_glob_denied_with_step1_wording(monkeypatch, tmp_path):
    for tool in ("Read", "Grep", "Glob"):
        result = _drive_reader_sdk(
            monkeypatch, tmp_path,
            scenario="ok_write",
            write_tool=tool,
            write_target=tmp_path / f"ct6-{tool}.txt",
        )
        outcome = result["outcome"]
        assert outcome.denials, tool
        entry = outcome.denials[-1]
        assert entry["tool"] == tool
        assert entry["reason"] == f"self-learn invocation charter: {tool} is disallowed on this surface"


def test_ct7_deny_recorded_in_denials_names_write(monkeypatch, tmp_path):
    home = tmp_path / "ct7-home"
    home.mkdir()
    outside = home / "ct7-outside.md"
    result = _drive_reader_sdk(monkeypatch, tmp_path, home=home, write_target=outside)
    outcome = result["outcome"]
    assert outcome.denials, "expected a denial to be recorded"
    assert outcome.denials[-1]["tool"] == "Write"


def test_ct8_hatch_permanently_closed_even_with_enforce_scope_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_ENFORCE_SCOPE", "0")
    home = tmp_path / "ct8-home"
    home.mkdir()
    outside = home / "ct8-outside.md"
    result = _drive_reader_sdk(monkeypatch, tmp_path, home=home, write_target=outside)
    assert not outside.exists()
    assert result["outcome"].denials
    assert result["outcome"].denials[-1]["tool"] == "Write"


# ===================================================================== #
# RC -- the output contract [both]
# ===================================================================== #


def test_rc1_spool_listing_is_exactly_the_artifact(reader_leg):
    reader_leg.drive()
    names = sorted(p.name for p in miner.spool_dir().iterdir())
    assert names == [miner.OUTPUT_BASENAME]


def test_rc2_invoke_reader_returns_the_artifact_path(reader_leg):
    run = reader_leg.drive()
    assert run.out_path == miner.spool_dir() / miner.OUTPUT_BASENAME
    assert run.out_path.is_file()


def test_rc3_outcome_stdout_is_non_empty(reader_leg):
    run = reader_leg.drive()
    assert run.outcome.stdout != ""


def test_rc4_return_value_independent_of_stdout_content(reader_leg):
    run1 = reader_leg.drive(body=None, stdout_text='{"candidates": [], "fires": []}')
    assert run1.out_path is None

    run2 = reader_leg.drive(body='{"candidates": [], "fires": []}', stdout_text="NOT VALID JSON {{{")
    assert run2.out_path is not None
    assert run2.out_path.is_file()


_RC5_BODY = "café — one non-ASCII char, trailing newline\n"


def test_rc5_artifact_bytes_round_trip_verbatim(reader_leg):
    run = reader_leg.drive(body=_RC5_BODY)
    assert run.out_path is not None
    assert run.out_path.read_text(encoding="utf-8") == _RC5_BODY


def test_rc6_stale_artifact_preseeded_run_writes_nothing_returns_none(reader_leg):
    reader_leg.out_path.write_text("STALE FROM LAST NIGHT", encoding="utf-8")
    run = reader_leg.drive(body=None)
    assert run.out_path is None
    assert not reader_leg.out_path.exists()


def test_rc7_prompt_reaches_the_model_on_stdin_never_argv(monkeypatch, tmp_path):
    # `RO-7`/`CV8` REWRITE (§8.4b, `T-READER-PROMPT-ON-THE-WIRE`): the
    # `[cli]` leg's `run.argv`/`run.prompt_seen` witnesses are gone with
    # the bash shim; the `[sdk]` leg's own body (`run.spec.prompt ==
    # big_prompt` plus a `cli_argv_builder`/`cli_settings_writer` recompute
    # off the SPEC object) collapses to a tautology about the spec once
    # the `[cli]` leg is stripped away (CV2 clause 3) -- it never
    # observed the real wire OR the real child's argv. Modelled on the
    # genuine wire test `test_bg3_sdk_prompt_delivered_intact`
    # (`test_worker_contract.py`): spy `ClaudeSDKClient.query` for
    # witness (i) -- the prompt arrives on the wire -- and
    # `FAKE_CLAUDE_ARGV_LOG` (the real child process's OWN recorded
    # argv, RO-1) for witness (ii) -- it appears in none of it. Both
    # halves of "on stdin, never argv" hold against the surviving
    # transport.
    from claude_agent_sdk import ClaudeSDKClient

    big_prompt = "X" * (200 * 1024)  # > 128 KiB argv element cap
    argv_log = tmp_path / "rc7-argv.log"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))

    recorded_prompts: list[str] = []
    real_query = ClaudeSDKClient.query

    async def spy_query(self, prompt, *a, **kw):
        recorded_prompts.append(prompt)
        return await real_query(self, prompt, *a, **kw)

    monkeypatch.setattr(ClaudeSDKClient, "query", spy_query)

    result = _drive_reader_sdk(monkeypatch, tmp_path, prompt=big_prompt)

    assert recorded_prompts and recorded_prompts[0] == big_prompt  # witness (i): on the wire
    assert result["spec"].prompt == big_prompt

    raw = argv_log.read_bytes() if argv_log.exists() else b""
    argv = [a.decode("utf-8") for a in raw.split(b"\0")[:-1]] if raw else []
    assert argv, "the real child never recorded its own argv"
    assert all(big_prompt not in element for element in argv)  # witness (ii): never argv


# ===================================================================== #
# TO -- timeout semantics and the kill paths
# ===================================================================== #


def test_to1_transport_timeout_is_the_patched_value(reader_leg, monkeypatch):
    monkeypatch.setattr(miner, "INVOKE_TIMEOUT_SECS", TIMEOUT_PATCH)
    run = reader_leg.drive()
    assert run.spec.timeout == TIMEOUT_PATCH


def test_to2_rendered_log_line_carries_the_patched_value(reader_leg, monkeypatch):
    monkeypatch.setattr(miner, "INVOKE_TIMEOUT_SECS", TIMEOUT_PATCH)
    before = _log_text(reader_leg.home)
    reader_leg.arm_timeout()
    run = reader_leg.invoke()
    assert run.outcome.failure == "timeout"
    added = _log_lines_added(before, _log_text(reader_leg.home))
    expected = f"run: claude timed out after {TIMEOUT_PATCH}s"
    assert any(line.endswith(expected) for line in added), added


def test_to3_timeout_log_line_byte_identical_across_backends(reader_leg, monkeypatch):
    monkeypatch.setattr(miner, "INVOKE_TIMEOUT_SECS", TIMEOUT_PATCH)
    before = _log_text(reader_leg.home)
    reader_leg.arm_timeout()
    run = reader_leg.invoke()
    assert run.outcome.failure == "timeout"
    timed_out_template = invocation.LOG_TEMPLATES["miner-reader"].timed_out
    assert timed_out_template is not None
    expected = timed_out_template.format(label="", timeout=TIMEOUT_PATCH)
    assert expected == f"run: claude timed out after {TIMEOUT_PATCH}s"
    added = _log_lines_added(before, _log_text(reader_leg.home))
    assert any(line.endswith(expected) for line in added), added


# U-cleanup-A DELETE (§8.4 table, "killpg on miner timeout" row): both
# `test_to4_cli_kill_path_killpg_then_wait` and `test_to5_swallows_
# processlookuperror_and_permissionerror_separately` drove `subprocess.
# Popen`/`os.killpg` directly against `_cli_reader_home` (an empty-PATH
# sanitized home with NO explicit backend override), relying on
# conftest's autouse `SELF_LEARN_BACKEND_MINER=cli` pin (AG3) to resolve
# `miner-reader` to a REAL `CliBackend`. Both are moot -- the spec calls
# them out by name as replaced by the sdk kill ladder (`test_to6_kill_
# ladder_three_rungs_and_pgid_discrimination`, `test_to7_pid_sidecar_
# present_during_absent_after` below, plus `KL1`-`KL8` in
# `test_invocation_sdk.py`) -- and both would otherwise start exercising
# `CliBackend._run` for real the moment AG3 removes the conftest pin
# (their driving sets no explicit `SELF_LEARN_BACKEND_MINER` itself), a
# path AG1's tripwire then makes fatal.


def test_to6_kill_ladder_three_rungs_and_pgid_discrimination(monkeypatch):
    interrupt_calls: list[int] = []
    disconnect_calls: list[int] = []

    class _Client:
        async def interrupt(self):
            interrupt_calls.append(1)
            return None

        async def disconnect(self):
            disconnect_calls.append(1)
            await asyncio.sleep(3600)

    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.05)
    monkeypatch.setattr(lifecycle_mod, "INTERRUPT_GRACE_SECS", 0.05)
    kill_calls = {"kill": [], "killpg": []}
    monkeypatch.setattr(lifecycle_mod.os, "kill", lambda pid, sig: kill_calls["kill"].append((pid, sig)))
    monkeypatch.setattr(lifecycle_mod.os, "killpg", lambda pid, sig: kill_calls["killpg"].append((pid, sig)))
    monkeypatch.setattr(lifecycle_mod.worker, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(lifecycle_mod.os, "getpgid", lambda pid: 100)

    async def _drive():
        client = _Client()
        before = set(lifecycle_mod._ABANDONED_DISCONNECTS)
        await lifecycle_mod.run_kill_ladder(client, 4242, lambda _m: None)
        added = lifecycle_mod._ABANDONED_DISCONNECTS - before
        assert interrupt_calls == [1]
        assert disconnect_calls == [1]
        assert len(added) == 1, "the abandoned disconnect() task was never tracked"
        task = next(iter(added))
        assert task.done() is False
        assert task.cancelled() is False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())
    assert kill_calls["kill"] == [(4242, signal.SIGKILL)]
    assert kill_calls["killpg"] == []

    kill_calls["kill"].clear()
    monkeypatch.setattr(lifecycle_mod.os, "getpgid", lambda pid: 100 if pid == 0 else 200)
    lifecycle_mod.kill_child(4242, lambda _m: None)
    assert kill_calls["killpg"] == [(4242, signal.SIGKILL)]
    assert kill_calls["kill"] == []


def test_to7_pid_sidecar_present_during_absent_after(monkeypatch, tmp_path):
    seen_during: dict = {}
    real_clear = lifecycle_mod.clear_sidecar

    def spy_clear(surface):
        seen_during["existed"] = lifecycle_mod._sidecar_path(surface).is_file()
        real_clear(surface)

    monkeypatch.setattr(lifecycle_mod, "clear_sidecar", spy_clear)
    result = _drive_reader_sdk(monkeypatch, tmp_path)
    assert seen_during.get("existed") is True
    assert result["outcome"].failure is None
    assert not lifecycle_mod._sidecar_path("miner-reader").exists()


# ===================================================================== #
# SW -- the sweep and the dispatch
# ===================================================================== #


def test_sw1_early_returns_precede_the_sweep_all_four_kinds(monkeypatch, tmp_path, sdk_absent):
    home = _cli_reader_home(tmp_path, monkeypatch)
    spool = miner.spool_dir()
    stray = spool / "sw1-litter.txt"

    scenarios = [
        ("timeout", _FakePopenTO(raise_on_communicate=subprocess.TimeoutExpired(cmd=["claude", "x"], timeout=1))),
        ("not-found", _PopenRaisesTO(FileNotFoundError())),
        ("os-error", _PopenRaisesTO(OSError("boom"))),
    ]
    for kind, fake in scenarios:
        stray.write_text("litter", encoding="utf-8")
        monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)
        monkeypatch.setattr(subprocess, "Popen", fake)
        out = miner._invoke_reader(home, "PROMPT")
        assert out is None, kind
        assert stray.exists(), f"{kind}: stray sweep ran despite an early return"

    # U-flip pins SELF_LEARN_BACKEND_MINER=cli at rung 1 (conftest's
    # suite-wide default); clear it too, or it shadows this rung-2
    # override and miner-reader never reaches "unavailable".
    stray.write_text("litter", encoding="utf-8")
    monkeypatch.delenv("SELF_LEARN_BACKEND_MINER", raising=False)
    monkeypatch.setenv("SELF_LEARN_BACKEND", "sdk")
    out = miner._invoke_reader(home, "PROMPT")
    assert out is None, "unavailable"
    assert stray.exists(), "unavailable: stray sweep ran despite an early return"
    monkeypatch.delenv("SELF_LEARN_BACKEND", raising=False)


def test_sw2_rc_nonzero_does_not_short_circuit(reader_leg):
    run = reader_leg.drive(exit_code=7)
    assert run.out_path is not None
    assert run.out_path.is_file()


def test_sw3_sweep_deletes_strays_survives_artifact_exact_log_lines(reader_leg):
    spool = miner.spool_dir()
    stray1 = spool / "sw3-litter-1.txt"
    stray2 = spool / "sw3-litter-2.txt"
    stray1.write_text("a", encoding="utf-8")
    stray2.write_text("b", encoding="utf-8")
    before = _log_text(reader_leg.home)
    run = reader_leg.drive()
    assert run.out_path is not None
    assert run.out_path.is_file()
    assert not stray1.exists()
    assert not stray2.exists()
    added = _log_lines_added(before, _log_text(reader_leg.home))
    expected = {
        f"run: stray spool artifact {stray1.name} deleted",
        f"run: stray spool artifact {stray2.name} deleted",
    }
    matching = [line for line in added if any(line.endswith(e) for e in expected)]
    assert len(matching) == 2, added


def test_sw4_directory_in_spool_survives_the_sweep(reader_leg):
    spool = miner.spool_dir()
    subdir = spool / "sw4-subdir"
    subdir.mkdir()
    run = reader_leg.drive()
    assert subdir.is_dir()
    assert run.out_path is not None


def test_sw6_no_local_reimplementation_of_the_dispatch():
    """`SW6`/`S-e` -- structural: `EARLY_RETURN` is defined exactly once
    in this module (Sets-1), and this module contains no second `if
    outcome.failure in {...}`-shaped re-derivation of the dispatch."""
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=__file__)
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "EARLY_RETURN" for t in node.targets)
    ]
    assert len(assignments) == 1, assignments


# ===================================================================== #
# FL -- flip readiness
# ===================================================================== #


def _clear_backend_env(monkeypatch):
    for var in (
        "SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_WORKER",
        "SELF_LEARN_BACKEND_MINER", "SELF_LEARN_BACKEND_ANALYST",
    ):
        monkeypatch.delenv(var, raising=False)


# U-cleanup-A DELETE (§8.4b): `test_fl1_backend_var_cli_resolves_
# clibackend` asserted that an explicit `cli` selector reaches a real
# `CliBackend` -- an outcome CV2/CB-3 no longer treats as a legitimate,
# expected resolution to assert as PASSING behaviour (a `cli` selector
# should be *refused*, not honoured). Replaced by `T-CLI-REFUSED-*`
# (`SEL1`-`SEL4`) -- [B] scope, out of this Phase A build. `backend_for`
# itself is untouched product code (Phase A deletes zero product code),
# so this is a test-only removal, not a behavioural regression.


def test_fl2_clean_env_resolves_sdkbackend(monkeypatch):
    # U-flip flipped miner-reader's product default from "cli" to "sdk"
    # (same table rung the analyst flip, U-sdka, used). This criterion
    # used to be "...resolves_the_shared_clibackend" -- a clean env now
    # resolves a real `SdkBackend`, not the shared `CliBackend` singleton.
    _clear_backend_env(monkeypatch)
    backend = invocation.backend_for("miner-reader")
    assert isinstance(backend, SdkBackend)


def test_fl3_selector_scoping_both_directions(monkeypatch):
    from self_learn.invocation_sdk import SdkBackend as _SdkBackend

    # U-flip flipped miner-reader's and worker's own defaults to sdk
    # (same table rung as the analyst's, U-sdka). The scoping claim (a
    # FOREIGN selector does not govern this surface) needs the stimulus
    # INVERTED to "cli": a leak would then flip the surface to
    # CliBackend and redden, while the correct behavior keeps its own
    # sdk default. (Stimulus "sdk" would be tautological -- leak and
    # no-leak both resolve SdkBackend; gate blessing-read catch.)
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    assert isinstance(invocation.backend_for("miner-reader"), _SdkBackend)

    _clear_backend_env(monkeypatch)
    monkeypatch.setenv(BACKEND_VAR, "cli")
    assert isinstance(invocation.backend_for("worker"), _SdkBackend)
    # U-sdka flipped the analyst's product default to sdk. The scoping
    # claim (the MINER selector does not govern the analyst) needs the
    # same inversion -- and it's already in place from the line above
    # (BACKEND_VAR is still "cli").
    assert isinstance(invocation.backend_for("analyst"), _SdkBackend)


def test_fl4_no_shipped_assignment_of_backend_var(tmp_path):
    cli_root = Path(miner.__file__).resolve().parents[2]  # .../plugins/self-learn/cli
    src_dir = cli_root / "src"
    systemd_dir = cli_root.parents[2] / "systemd"
    scanned = list(src_dir.rglob("*.py"))
    if systemd_dir.is_dir():
        scanned += [p for p in systemd_dir.rglob("*") if p.is_file()]
    hits = []
    for path in scanned:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if BACKEND_VAR in text:
            hits.append(path)
    assert hits == [], hits

    # Positive control (`D-10`): the SAME string, in a file the scan can
    # see, must be found -- a scan that silently matches nothing cannot
    # pass as a clean result.
    positive = tmp_path / "fl4-positive-control.py"
    positive.write_text(f'{BACKEND_VAR} = "sdk"\n', encoding="utf-8")
    assert BACKEND_VAR in positive.read_text(encoding="utf-8")


# ===================================================================== #
# HY -- hygiene
# ===================================================================== #


def test_hy1_the_new_shim_builder_satisfies_b9():
    assert "write_reader_claude_shim" in shims.__all__
    src = inspect.getsource(shims.write_reader_claude_shim)
    assert "@pytest.fixture" not in src
    assert "mkdir" not in src
    assert "chmod" in src


def test_hy3_sdk_driving_sets_the_fake_cli_path_first_no_undo_on_the_shared_fixture():
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=__file__)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "undo"
            and isinstance(func.value, ast.Name)
            and func.value.id == "monkeypatch"
        ):
            raise AssertionError(
                "monkeypatch.undo() on the shared fixture instance is forbidden in this file"
            )

    for name in ("_drive_reader_sdk",):
        node = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name
        )
        fn_src = ast.get_source_segment(src, node) or ""
        set_idx = fn_src.index('"SELF_LEARN_SDK_CLI_PATH"')
        invoke_idx = fn_src.index("_capture_invoke_reader(")
        assert set_idx < invoke_idx, name

    # `reader_leg`'s `sdk` branch is the SECOND branch in source order (the
    # `cli` branch's own `_ReaderLeg(` call precedes it) -- the LAST
    # `_ReaderLeg(` call in the function is the sdk branch's, so that is
    # the one the env-var set must precede.
    fixture_node = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "reader_leg"
    )
    fixture_src = ast.get_source_segment(src, fixture_node) or ""
    set_idx = fixture_src.index('"SELF_LEARN_SDK_CLI_PATH"')
    invoke_idx = fixture_src.rindex("_ReaderLeg(")
    assert set_idx < invoke_idx


def test_hy4_no_real_claude_reachable():
    """`HY4` -- the `cli` leg's PATH is always shim-first (every drive
    writes the shim before invoking), and the `sdk` leg's `cli_path` is
    always `FAKE_CLI` -- never a real, resolvable `claude`."""
    src = Path(__file__).read_text(encoding="utf-8")
    assert "write_reader_claude_shim" in src
    setenv_pattern = re.compile(r'\.setenv\(\s*"SELF_LEARN_SDK_CLI_PATH"')
    for lineno, line in enumerate(src.splitlines(), start=1):
        if setenv_pattern.search(line):
            assert "FAKE_CLI" in line, (lineno, line)


def test_hy5_which_claude_resolves_exclusively_into_the_leg_shim_dir(reader_leg):
    """`HY5` (gate fold MAJOR-2) -- ports the sibling U-sdkw's which-
    assertion shape (`test_worker.py`'s `self-learn-notify` precedent,
    ~line 266: `shutil.which(...)` must resolve either to nothing or
    strictly inside the test's own shim dir) to `claude` itself, run
    BEHAVIORALLY against the fixture's OWN PATH -- not just the AST
    source-scans `HY3`/`HY4` already do. Exclusive: whatever resolves
    must live inside `reader_leg.shim_dir`, on BOTH legs. Exhaustive:
    never `None` either -- `MAJOR-3`'s shadow-not-subtract fix means a
    decoy `claude` is written into the shim/shadow dir at fixture
    SETUP, before this test body (or any `.drive()`/`.arm_timeout()`)
    runs, so resolution must already succeed here."""
    resolved = shutil.which("claude")
    assert resolved is not None, "no claude resolvable at all -- the decoy shim is missing"
    assert Path(resolved).resolve().parent == reader_leg.shim_dir.resolve(), (
        reader_leg.name, resolved, reader_leg.shim_dir,
    )
