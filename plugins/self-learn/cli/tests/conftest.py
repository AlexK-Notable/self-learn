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


#: U-cleanup-B: `_cli_backend_unreached_tripwire` (U-cleanup-A `AG1`) is
#: RETIRED here, exactly as its own docstring said it would be -- its
#: subject, `CliBackend._run`, no longer exists (§8.1), so there is
#: nothing left to guard being unreached. `AG2`'s negative control
#: (`test_u_sdka.py::test_ag2_tripwire_fires_on_direct_clibackend_call`)
#: is deleted alongside it, not retargeted -- it existed solely to prove
#: THIS tripwire arms, and there is no tripwire left to prove.


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
    # Config isolation for EVERY test (found 2026-08-27, U-servehermetic:
    # `serve.unit_dir()` falls back to `XDG_CONFIG_HOME`, then to the
    # real `~/.config/systemd/user`, exactly mirroring the cache-isolation
    # reasoning above -- without this, a test session on a host that has
    # ever linked the `self-learn-host.service` reference unit reads that
    # REAL unit as "configured" and produces a live-host-dependent FAIL/
    # SKIP split invisible to the U-engine Phase 2 gate, which ran before
    # any host had linked the unit). Tests that redirect XDG themselves
    # simply override this default, same convention as XDG_CACHE_HOME.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-default"))
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
    # U-cleanup-A `AG3`: the three suite-wide `cli` pins that used to sit
    # here (U-sdka `Armor-1`'s analyst pin, U-flip's worker/miner pins)
    # are REMOVED, not merely edited. Their premise was "every
    # pre-existing test drives a bash PATH shim or a patched
    # `subprocess.run`, i.e. the cli transport, and names no backend" --
    # CV2/CB-3's migration has made that premise false: the ~109
    # behaviour tests now drive `SdkBackend` -> `fake_claude.py`
    # end to end (`sdk_fake_worker`/`sdk_fake_analyst`,
    # `reader_leg`, `backend`). With no pin left here, EVERY surface now
    # resolves through `DEFAULT_BACKEND_FOR_SURFACE` (all `sdk` since
    # U-flip) unless a test overrides it.
    # U-cleanup-B (code gate r1, NIT-5): this paragraph used to end by
    # pointing at "the suite-wide default this unit's own `AG1`
    # tripwire on `CliBackend._run` is meant to prove unreached in
    # practice, not merely in theory" and "every remaining test that
    # still needs `cli` for real names it explicitly via its own
    # `monkeypatch.setenv`" -- both stale. `AG1`/`_cli_backend_
    # unreached_tripwire` is RETIRED (see the docstring 30 lines above
    # this fixture); `CliBackend._run` no longer exists to be reached
    # or unreached. And no test "needs `cli` for real" any more --
    # `cli` is a NAMED REFUSAL now (`registry._resolve`), never a
    # second transport a test could drive; the handful of tests that
    # still `monkeypatch.setenv(..., "cli")` (SEL1-6, the scoping-
    # precedence tests) are asserting the refusal fires, not reaching
    # a real subprocess.
