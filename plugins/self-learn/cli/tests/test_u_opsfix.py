"""U-opsfix (task note 3pKzmkglwvyogdBYQqJaV) — two of the unit's three
surgical fixes:

- FW-108: `invocation_sdk/backend.py`'s `CharterPatternUnsupported`
  handler in `_drive` (~:411) returned the `os-error` `Outcome` WITHOUT
  rendering `LOG_TEMPLATES[surface].os_error` to the operator log,
  unlike the `ClaudeSDKError`/`OSError` handlers right below it.
- FW-107: `worker.py`'s `run: FAILED — …` summary line (~:3438, byte-
  pinned by `test_repair.py::test_h3_the_five_existing_log_lines_are_
  byte_stable`) could not tell a fully-charter-denied run apart from
  one that wrote nothing at all.

Q2 (`confirm_recurrence`'s cross-record hole) is tested separately, in
`tests/test_dismiss_suspect.py` — it mirrors that file's own
T-EVENT-BELONGS test for the sibling verb `dismiss_suspect`, the more
natural home for a `confirm_recurrence`/`dismiss_suspect` parity test.

Armor (`test_worker_contract.py::_ARMOR_SHAS`) pins conftest.py,
backends.py, test_invocation.py, test_invocation_sdk.py, test_u_fake.py,
test_worker.py, test_repair.py byte-for-byte — none of those seven files
are edited by this unit. Shared fixtures/constants this file needs from
them (`env`, `seed_pending`, `shim_writes`, `sdk_fake_worker`, `FAKE_CLI`,
`sdk_cli_path`) are imported BY NAME, the same established pattern every
sibling contract-test file already uses (`test_worker_contract.py`,
`test_invocation_sdk.py` import from `test_worker.py` the same way). The
CharterPatternUnsupported drive and the charter-denial fixture shape are
REPLICATED locally (not imported) per the build task's own instruction,
since both live inside pinned files.
"""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

from self_learn import invocation, worker
from self_learn.invocation.contract import (
    LOG_TEMPLATES,
    Containment,
    SessionSpec,
    containment_for,
)
from self_learn.invocation_sdk import SdkBackend, SdkOutcome
from self_learn.invocation_sdk import backend as backend_mod

from test_invocation_sdk import sdk_cli_path  # noqa: F401 -- fixture resolved by name
from test_worker import (  # noqa: F401 -- fixtures resolved by name
    env,
    sdk_fake_worker,
    seed_pending,
)

# ===================================================================== #
# FW-108 — the CharterPatternUnsupported leg logs like its siblings
# ===================================================================== #

_WORKER_ALLOWED = "Read,Grep,Glob"
_WORKER_DISALLOWED = "Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"


def _worker_containment(home: Path) -> Containment:
    return containment_for(
        "worker",
        allowed_tools=_WORKER_ALLOWED,
        disallowed_tools=_WORKER_DISALLOWED,
        home=str(home),
        stage_dir=home / "stage",
        stage_on=False,
        enforce=True,
    )


def test_fw108_charter_pattern_unsupported_logs_the_os_error_line(
    tmp_path, sdk_cli_path, monkeypatch
):
    """`_build_options` raises `CharterPatternUnsupported` for a
    malformed `write_globs` pattern (the SAME `/tmp/[x]/**` shape
    `test_invocation_sdk.py::test_ou1_every_row_of_the_map_1_table`
    drives for its `CharterPatternUnsupported` leg — replicated here,
    not imported, because that test lives in a pinned file) — this
    happens inside `_build_options`, BEFORE any `ClaudeSDKClient` is
    constructed (`C-7`/`CH7`). The fix: this leg now renders
    `LOG_TEMPLATES["worker"].os_error` through `spec.log`, same as the
    `ClaudeSDKError`/`OSError` handlers a few lines below it always did,
    while the returned `Outcome` and the no-session-started property are
    UNCHANGED."""
    home = tmp_path / "fw108-home"
    home.mkdir()

    constructed: list[object] = []

    class _Spy(ClaudeSDKClient):
        def __init__(self, *, options):
            constructed.append(options)
            super().__init__(options=options)

    monkeypatch.setattr(backend_mod, "ClaudeSDKClient", _Spy)

    template = LOG_TEMPLATES["worker"].os_error
    assert template is not None
    # The template minus its `{exc}` slot — a deterministic prefix every
    # rendering of this line must start with, regardless of the
    # exception's own (pattern-dependent) message text.
    expected_prefix = template.format(label="", exc="")[:-1]

    bad = Containment(
        allowed_tools=None,
        disallowed_tools="Bash",
        write_globs=("/tmp/[x]/**",),
        write_exact=(),
        strict_mcp=True,
        default_mode="default",
    )
    logged: list[str] = []
    spec = SessionSpec(
        surface="worker",
        prompt="ok_text",
        cwd=home,
        timeout=20.0,
        containment=bad,
        log=logged.append,
        label="",
        doctrine=None,
    )
    outcome = SdkBackend().write_session(spec)

    # The Outcome, its failure kind, and the no-session-started property
    # are UNCHANGED by this fix.
    assert isinstance(outcome, SdkOutcome)
    assert outcome.ok is False
    assert outcome.rc is None
    assert outcome.stdout == ""
    assert outcome.failure == "os-error"
    assert constructed == [], "no ClaudeSDKClient may ever be constructed for this leg"

    # FW-108 itself: the os_error template line now appears, exactly
    # once, in the spec's log.
    assert len(logged) == 1
    assert logged[0].startswith(expected_prefix)

    # Positive control: a run that does NOT raise CharterPatternUnsupported
    # (a valid containment) emits no such line — and DOES construct a
    # session, proving the spy above actually intercepts real
    # construction rather than passing vacuously.
    constructed.clear()
    logged.clear()
    ok_spec = SessionSpec(
        surface="worker",
        prompt="ok_text",
        cwd=home,
        timeout=20.0,
        containment=_worker_containment(home),
        log=logged.append,
        label="",
        doctrine=None,
    )
    ok_outcome = SdkBackend().write_session(ok_spec)
    assert ok_outcome.ok is True
    assert constructed, "the positive control must actually start a session"
    assert not any(line.startswith(expected_prefix) for line in logged)


def test_fw108_no_line_when_surface_does_not_catch_os_error(tmp_path, sdk_cli_path, monkeypatch):
    """M-1 (gate r1) follow-on: the ruled guard is
    `_CATCHES_OS_ERROR.get(surface, True) and templates.os_error is not
    None` -- when a surface's `_CATCHES_OS_ERROR` entry is False, no
    line is rendered (the returned `Outcome` is unaffected either way)."""
    home = tmp_path / "fw108-guard-home"
    home.mkdir()
    monkeypatch.setitem(backend_mod._CATCHES_OS_ERROR, "worker", False)

    bad = Containment(
        allowed_tools=None, disallowed_tools="Bash", write_globs=("/tmp/[x]/**",),
        write_exact=(), strict_mcp=True, default_mode="default",
    )
    logged: list[str] = []
    spec = SessionSpec(
        surface="worker", prompt="ok_text", cwd=home, timeout=20.0,
        containment=bad, log=logged.append, label="", doctrine=None,
    )
    outcome = SdkBackend().write_session(spec)
    assert outcome.ok is False
    assert outcome.failure == "os-error"
    assert logged == []


# ===================================================================== #
# FW-107 — a fully-denied run is no longer indistinguishable from a
# wrote-nothing run
# ===================================================================== #

#: `test_repair.py::test_h3_the_five_existing_log_lines_are_byte_stable`
#: pins this exact text; it must appear verbatim, unchanged, in both
#: legs below.
_FAILED_LINE = (
    "run: FAILED — 1 eligible, 0 valid proposals (last-run not touched; "
    "staleness alarm is the detector)"
)


def test_fw107_fully_denied_run_gets_a_charter_denial_line(env, sdk_cli_path, monkeypatch):
    """Same drive `test_worker_contract.py::test_ws2_sdk_charter_
    frontier_matches_scope1` case B uses to produce a REAL, end-to-end
    charter denial (replicated here — that test lives in a pinned
    file): `FAKE_CLAUDE_FORCE_SCENARIO=ok_write` makes the fake CLI
    issue a real `can_use_tool` control request for a `Write` whose
    target is a ledger `proposals/` path — outside the batch round's
    stage-only write scope — so the charter denies it. Nothing lands;
    the run is FAILED; the new line names the denial."""
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")
    monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "ok_write")
    monkeypatch.setenv("SELF_LEARN_REPAIR", "0")  # isolate to round 1 only

    rid = seed_pending(env)
    ledger_target = env.proposals / f"{rid}.yaml"
    monkeypatch.setenv("FAKE_CLAUDE_WRITE_TARGET", str(ledger_target))

    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")

    # N-2 (gate r1): the line is locatable -- no `run_id` is in scope
    # in worker.py, so the glob is paired with the resolved cache dir.
    expected_denial_line = (
        f"run: 1 charter denial(s) this run — see worker*.tool-events.*.jsonl "
        f"in {worker.cache_dir()}"
    )
    assert _FAILED_LINE in log_text
    assert expected_denial_line in log_text
    assert not ledger_target.exists()


def test_fw107_wrote_nothing_run_has_no_denial_line(env, sdk_fake_worker, monkeypatch):
    """Positive control: `test_repair.py::test_h3_...`'s own wrote-
    nothing-but-FAILED shape (an invalid model proposal — no charter
    involvement at all; `shim_script`'s writes are never gated on the
    charter, `fake_claude.py`'s own `R2-N3` note) reaches the SAME
    FAILED line with NO denial line — a denied run and a wrote-nothing
    run were the exact pair FW-107 could not tell apart."""
    rid = seed_pending(env)
    bad = worker.stage_dir() / f"{rid}.yaml"
    monkeypatch.setenv(
        "CLAUDE_SHIM_SCRIPT",
        f"mkdir -p {bad.parent} && printf 'destination: bogus\\n' > {bad}",
    )
    worker.run(env.home)
    log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")

    assert _FAILED_LINE in log_text
    assert "charter denial(s)" not in log_text


def test_fw107_sdk_result_denials_are_not_charter_denials(monkeypatch, tmp_path):
    """N-3 (gate r1), the inverse of the fully-denied case: the filter
    inside `_invoke_claude` is `source == "charter"` ONLY. A denial
    `EventLog.add_sdk_permission_denial` records (`source ==
    "sdk-result"` -- the SDK's own `ResultMessage.permission_denials`,
    never seen by the charter callback) must NOT count toward the new
    line. Exercised directly against `_invoke_claude`'s `charter_denials`
    side channel with a stand-in `SdkOutcome` (cheaper and more precise
    than driving a real `permission_denials`-carrying session end to
    end) -- this is the exact filter FW-107 added, so it is what needs a
    positive control in the other direction."""
    from self_learn.invocation_sdk import SdkOutcome

    fake_outcome = SdkOutcome(
        ok=True, rc=0, stdout="", detail="", failure=None,
        denials=({"source": "sdk-result", "value": {"tool_name": "Bash"}},),
    )
    monkeypatch.setattr(invocation, "write_session", lambda spec, **kw: fake_outcome)

    home = tmp_path / "fw107-n3-home"
    home.mkdir()
    charter_denials: list = []
    worker._invoke_claude(
        "prompt", 5.0, home, label="",
        containment=invocation.DEGRADED_WORKER_CONTAINMENT,
        charter_denials=charter_denials,
    )
    assert charter_denials == []
