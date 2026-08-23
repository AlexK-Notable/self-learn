"""Suite-wide defaults.

The M2 worker is kick-driven: real `teach`/`import` end by spawning a
detached coalescing run. Tests must never leak detached processes, so
auto-kick is disabled globally here; worker tests opt back in (or drive
`worker.kick`/`worker.run` directly) by clearing/overriding the env var.
Coalesce sleep is zeroed for the same reason.

Incident 2026-08-09: notifications are ALSO suppressed globally here
(`SELF_LEARN_NO_NOTIFY=1`, same convention as AUTOKICK above) — both
`worker._notify` and `worker._notify_with_ids` resolve their helper via
PATH, which on a dev machine finds the REAL deployed ~/bin scripts
regardless of sandboxing, so an unsuppressed worker test notified the
operator's REAL desktop. Tests exercising notify behavior opt back out
via `monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)` — same
convention as AUTOKICK — and use the PATH-shimmed
`self-learn-notify`/`notify-send`, never the real ones.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _no_real_sdk_spawn_tripwire():
    """U-sdk code-gate fold, BLOCKER-1 fix-proof. `claude_agent_sdk`'s
    `_find_cli()` is the ONLY mechanism in this codebase that can resolve
    a `None` `cli_path` to a REAL, credentialed Claude Code binary
    (`_bundled/claude` or `shutil.which("claude")`) -- exactly the
    mechanism BLOCKER-1 exploited (a stray `monkeypatch.undo()` reverted
    `sdk_cli_path`'s `SELF_LEARN_SDK_CLI_PATH` mid-test, so `cli_path`
    fell through to `None` and the SDK silently spawned a real, ~4s,
    uncapped-budget session under the operator's own credentials).

    Every legitimate SDK-driving test in this suite sets
    `SELF_LEARN_SDK_CLI_PATH` (via `test_invocation_sdk.py`'s
    `sdk_cli_path` fixture), which flows into `ClaudeAgentOptions.cli_path`
    and keeps `self._cli_path` non-`None` at `connect()` time -- so
    `_find_cli()` should NEVER be called during this test session. Hard-
    blocking it turns a silent, timing-dependent real-session hazard into
    an immediate, deterministic test failure the instant the bug's class
    recurs, rather than a hope that a `ps` sampler catches a ~4s window.

    Lives HERE (not in `test_invocation_sdk.py`) so it is shared test
    infrastructure, not an `autouse` fixture inside the unit's own file
    (`Sim-1a` forbids that specifically in `test_invocation_sdk.py`).
    `claude_agent_sdk` is imported lazily and guarded -- this fixture must
    not fail collection in an environment where the SDK is absent."""
    try:
        import claude_agent_sdk._internal.transport.subprocess_cli as _subprocess_cli
    except ImportError:
        yield
        return

    def _tripped(self):
        raise AssertionError(
            "claude_agent_sdk._find_cli() was called during the test suite. "
            "This resolves cli_path=None to a REAL, credentialed Claude Code "
            "binary (_bundled/claude or PATH) -- exactly the hazard U-sdk's "
            "code-gate BLOCKER-1 found. Every session-driving test must set "
            "SELF_LEARN_SDK_CLI_PATH (the sdk_cli_path fixture) BEFORE the "
            "session runs, and must never call monkeypatch.undo() on the "
            "shared fixture instance -- use a nested pytest.MonkeyPatch() "
            "context for state that needs to unwind mid-test instead."
        )

    original = _subprocess_cli.SubprocessCLITransport._find_cli
    _subprocess_cli.SubprocessCLITransport._find_cli = _tripped
    try:
        yield
    finally:
        _subprocess_cli.SubprocessCLITransport._find_cli = original


@pytest.fixture(autouse=True)
def _worker_test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_LEARN_WORKER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "0")
    monkeypatch.setenv("SELF_LEARN_NO_NOTIFY", "1")
    # Cache isolation for EVERY test (found 2026-07-15: status tests read
    # the real ~/.cache worker.last-run once a real worker run existed on
    # the machine — the suite must never see real cache state). Tests that
    # redirect XDG themselves simply override this default.
    # MINOR 4 (code gate): before `init` existed no verb could CREATE a
    # home, so an unset SELF_LEARN_HOME was harmless. It no longer is.
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "home-default"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache-default"))
    # Miner defaults: no detached watchdog spawns, and the transcript root
    # NEVER defaults to the real ~/.claude/projects inside tests.
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv(
        "SELF_LEARN_TRANSCRIPTS_DIR", str(tmp_path / "_no_transcripts")
    )
    # The selftest hook check reads settings.json + ~/.claude/hooks (M3):
    # tests must never see the real ~/.claude — redirect it per-test.
    monkeypatch.setenv(
        "SELF_LEARN_CLAUDE_DIR", str(tmp_path / "claude-dir-default")
    )
    # U-sdka `Armor-1`: the analyst's SHIPPED default backend is now
    # `sdk` (invocation/contract.py `DEFAULT_BACKEND_FOR_SURFACE`). Every
    # pre-existing analyst test drives a bash PATH shim or a patched
    # `subprocess.run`, i.e. the cli transport, and names no backend --
    # same convention as SELF_LEARN_WORKER_AUTOKICK and
    # SELF_LEARN_NO_NOTIFY above: the suite opts OUT of real machinery by
    # default and a test that wants it opts back IN. `test_u_sdka.py`'s
    # FL1 asserts the PRODUCT default directly, with this var cleared.
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
    # U-flip: worker/worker-repair/miner-reader's SHIPPED default backend
    # is now ALSO `sdk` (same table). Same reasoning as the analyst pin
    # above -- every pre-existing worker/miner test drives a bash PATH
    # shim, a patched `subprocess.run`, or the in-process fake, i.e. the
    # cli transport, and names no backend. `SELF_LEARN_BACKEND_WORKER`
    # covers both `worker` and `worker-repair` (one selector, per
    # `SELECTOR_FOR_SURFACE`).
    monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
