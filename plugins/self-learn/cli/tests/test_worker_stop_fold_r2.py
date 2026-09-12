"""Gate r2 MINOR-B (§7.2a.5(4)): `worker.run`'s own start-of-run
`intents.recover` check already reports a PRE-EXISTING STOP as
`status="stopped"` (`test_intents.py::TestWorkerRunFindsAnIntent`
covers that). This file covers the gap the gate found: a STOP that
appears AFTER that start check finds nothing, but BEFORE `_harvest`
reaches for its own `intents.ledger_write` acquisition — a genuinely
MID-run STOP. `LedgerStoppedError` is a `gitops.GitOpsError` subclass,
so without a dedicated arm ahead of the generic one, this used to
degrade silently into "commit failed"/"could not take the ledger
lock" and never reach `serve._log_stopped_refusal`.

Deliberately its OWN file, not `test_worker.py` or `test_intents.py`:
the fold instruction pins `test_worker.py` unedited, and both of those
files already define their own `env` fixture with a shape this test's
`sdk_fake_worker` dependency (imported by NAME from `test_worker.py`,
same convention `test_settings.py`/`test_repair.py` already use) would
collide with.
"""

from __future__ import annotations

from self_learn import intents, worker
from support import commit_all, git, make_env

from test_worker import env, sdk_fake_worker, seed_pending, shim_writes  # noqa: F401


def test_run_a_stop_planted_mid_run_reports_stopped_not_failed(env, sdk_fake_worker, monkeypatch):
    """Plants the stop-shape recipe (mutate -> commit -> mutate again,
    uncompleted -- unresolvable anywhere) INSIDE a wrapper around
    `intents.ledger_write`, `_harvest`'s own call and the only one
    `run()` reaches on this path: the wrapper plants it, then delegates
    to the REAL function, so genuine recovery raises for real -- this
    is not a mocked STOP, only its timing is engineered."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))

    probe = env.home / "probe.txt"
    probe.write_text("seed\n", encoding="utf-8")
    commit_all(env.home, "add probe.txt")
    real_ledger_write = intents.ledger_write
    planted = {}

    def wrapper(home, **kw):
        if "intent" not in planted:
            intent = intents.begin(home, "probe", [probe], "self-learn: probe")
            probe.write_text("mutated once\n", encoding="utf-8")
            git(home, "add", "--", str(probe))
            git(home, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
            probe.write_text(
                "mutated once\nmutated twice, still uncompleted\n", encoding="utf-8"
            )
            planted["intent"] = intent
        return real_ledger_write(home, **kw)

    monkeypatch.setattr(intents, "ledger_write", wrapper)

    result = worker.run(env.home)

    assert result.status == "stopped"
    assert result.stopped
    assert planted["intent"].id in result.stopped[0]


def test_run_a_healthy_run_is_unaffected_by_the_new_arm(env, sdk_fake_worker, monkeypatch):
    """Positive control: the SAME wrapper shape, with nothing planted,
    changes nothing about the ordinary success path."""
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))

    result = worker.run(env.home)

    assert result.status == "ok"
    assert result.proposed == [rid]


def test_commit_locked_reports_stopped_not_a_commit_failure(tmp_path):
    """`_commit_locked`'s own arm (worker.py ~2452): reached STANDALONE
    via `_commit_run` (its own docstring: "which is why it can still be
    called on its own -- the miner's and the tests' path"), so this
    acquisition is genuinely OUTERMOST and a planted STOP raises for
    real, no monkeypatch needed."""
    ledger_env = make_env(tmp_path)
    home = ledger_env.ledger
    probe = home / "probe.txt"
    probe.write_text("seed\n", encoding="utf-8")
    commit_all(home, "add probe.txt")
    intent = intents.begin(home, "probe", [probe], "self-learn: probe")
    probe.write_text("mutated once\n", encoding="utf-8")
    git(home, "add", "--", str(probe))
    git(home, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
    probe.write_text("mutated once\nmutated twice, still uncompleted\n", encoding="utf-8")

    proposal = home / "skills" / "s" / "proposals" / "lrn-dddd0001.yaml"
    proposal.parent.mkdir(parents=True, exist_ok=True)
    proposal.write_text("destination: skill-md\n", encoding="utf-8")
    result = worker.RunResult(status="ok")
    result.touched = [proposal]
    result.valid_landed = 1

    worker._commit_run(home, result)  # must not raise

    assert result.status == "stopped"
    assert result.stopped
    assert intent.id in result.stopped[0]
    assert result.commit_sha is None
