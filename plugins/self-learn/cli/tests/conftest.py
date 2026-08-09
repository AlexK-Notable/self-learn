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
