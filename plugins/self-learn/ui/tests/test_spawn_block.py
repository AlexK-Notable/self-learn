"""The UI suite's spawn block (cli/tests/conftest.py has the CLI twin).

Every ledger-writing `self-learn` verb ticks the miner watchdog first and
spawns a real `mine run` when the last run is >24 h old (a scratch cache
has never run, so it is always due). A real miner reads real transcripts
and can make real model calls, which no test may do.

The env is built AFTER stripping the autouse fixture's pins from
`os.environ`, so this proves `support.make_env`'s own pins -- the case of a
module-scoped fixture or a probe that builds an env outside the autouse
fixture -- not the fixture's.
"""

from __future__ import annotations

import subprocess

import pytest

from self_learn_ui import ledger

from support import make_env

_PINS = (
    "SELF_LEARN_WORKER_AUTOKICK",
    "SELF_LEARN_MINER_AUTOKICK",
    "SELF_LEARN_NO_NOTIFY",
    "SELF_LEARN_TRANSCRIPTS_DIR",
)


def test_ledger_verb_through_sandbox_env_spawns_no_miner(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _PINS:
        monkeypatch.delenv(var, raising=False)
    sb = make_env(tmp_path)
    for var in _PINS:
        assert var in sb.env, var
    cache = tmp_path / "cache"

    # `list` is a read verb that still ticks the watchdog; the miner is due
    # (no run has ever completed in this scratch cache).
    proc = subprocess.run(
        [ledger._self_learn_bin(), "list"],
        capture_output=True, text=True, env=sb.env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "catch-up run spawned" not in proc.stderr
    # Anything under the cache means a verb reached the spawn lock; the
    # lock file is created only past the autokick switch.
    assert not list(cache.rglob("miner.spawn.lock")), list(cache.rglob("*"))
    assert not list(cache.rglob("miner*.log")), list(cache.rglob("*"))
