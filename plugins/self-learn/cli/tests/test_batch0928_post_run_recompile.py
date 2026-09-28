"""Batch 2026-09-28, unit F: a runner's owed host writes are recompiled
without a person.

The user's words (2026-09-28 11:54 PDT): "fix the rest of 3". A steward or
overseer run that applied a route whose host commit was refused (sweep 2
R3 puts the host file back and says "run `self-learn recompile`") left the
host target stale until a person ran that command. Now, after a run that
applied a route, rehome or rescope, the runner itself runs ONE recompile of
those records' own targets (`only_records`, sweep 2 R2), journals it, never
lets it raise out of the run, and reports a target it skips -- no retry
loop.

Sandbox ledger and host repos under pytest's tmpdir; fake model sessions;
the refusing git hook is a repo-local ``core.hooksPath``.
"""

from __future__ import annotations

import json
import os

import pytest

from self_learn import steward, verbs
from self_learn.records import Record
from support import git, make_env
from test_steward import _enable_steward
from test_steward_refusals import _dispositions, _notifications, _seed, _writer


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")


def _refusing_hook(tmp_path, host, *, times: int | None):
    """A pre-commit hook that refuses the first *times* commits (every
    commit when *times* is None), counting in a file outside the repo."""
    hooks = tmp_path / "refusing-hooks"
    hooks.mkdir(exist_ok=True)
    counter = tmp_path / "refusals"
    counter.write_text("0", encoding="utf-8")
    limit = "999999" if times is None else str(times)
    script = hooks / "pre-commit"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"n=$(cat '{counter}')\n"
        f"if [ \"$n\" -lt {limit} ]; then\n"
        f"  echo $((n+1)) > '{counter}'\n"
        "  echo 'test-hook: REFUSED the staged changes' >&2; exit 1\n"
        "fi\nexit 0\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    git(host, "config", "core.hooksPath", str(hooks))


def _status(host) -> str:
    return git(host, "status", "--porcelain", "-uall").stdout.strip()


def _journal_rows(home, status):
    path = steward.journal_path(home)
    return [
        row for row in (json.loads(line) for line in path.read_text().splitlines())
        if row.get("status") == status
    ]


def _route_run(tmp_path, monkeypatch, rid):
    env = make_env(tmp_path)
    home = env.ledger
    _seed(home, rid)
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [
            (rid, [rid], [{"id": rid, "verb": "route", "dest": "skill-md"}], "route", "route"),
        ]),
    )
    skill_md = env.skill_dir / "SKILL.md"
    return env, home, skill_md


@pytest.mark.parametrize("hooked", [False, True])
def test_a_route_whose_host_commit_was_refused_once_lands_after_the_run(
    tmp_path, monkeypatch, hooked
):
    """The route's own host commit is refused once (a transient refusal:
    a hook, a stale index.lock); the host file is put back (R3). Before,
    the SKILL.md stayed without the lesson until a person ran recompile.
    Now the post-run recompile lands it, and the journal says so."""
    rid = "lrn-f0000001"
    env, home, skill_md = _route_run(tmp_path, monkeypatch, rid)
    if hooked:
        _refusing_hook(tmp_path, env.host, times=1)

    result = steward.run(home)

    assert _dispositions(home, result.run_id)[rid]["state"] in ("applied", "unresolved-host")
    assert Record.from_path(home / "skills/s/resolved" / f"{rid}.md").status == "routed"
    assert rid in skill_md.read_text()
    assert _status(env.host) == ""
    assert result.recompile_skipped == []
    (row,) = _journal_rows(home, "recompile")
    assert row["run_id"] == result.run_id and row["records"] == [rid]
    assert row["skipped"] == []
    if hooked:
        # the route's own commit was refused; the post-run pass wrote it
        assert (tmp_path / "refusals").read_text().strip() == "1"
        assert row["changed"] == [str(skill_md)]
        assert git(env.host, "log", "-1", "--format=%s").stdout.startswith(
            "self-learn: recompile"
        )
    else:
        # control: the route wrote it; the pass found nothing stale
        assert row["changed"] == []


def test_a_target_the_pass_cannot_write_is_reported_not_retried(tmp_path, monkeypatch):
    """The hook refuses every commit: the run still completes, the host is
    left as it was, and the skipped target is in the run's result and its
    journal row, with the hook's message -- one pass, not a loop."""
    rid = "lrn-f0000002"
    env, home, skill_md = _route_run(tmp_path, monkeypatch, rid)
    _refusing_hook(tmp_path, env.host, times=None)
    before = skill_md.read_bytes()

    result = steward.run(home)

    assert Record.from_path(home / "skills/s/resolved" / f"{rid}.md").status == "routed"
    assert skill_md.read_bytes() == before
    assert _status(env.host) == ""
    # the route's commit, then exactly one post-run attempt
    assert (tmp_path / "refusals").read_text().strip() == "2"
    assert len(result.recompile_skipped) == 1
    assert str(skill_md) in result.recompile_skipped[0]
    assert "test-hook: REFUSED the staged changes" in result.recompile_skipped[0]
    (row,) = _journal_rows(home, "recompile")
    assert row["skipped"] == result.recompile_skipped


def test_a_recompile_that_raises_never_escapes_the_run(tmp_path, monkeypatch):
    rid = "lrn-f0000003"
    _env, home, _skill_md = _route_run(tmp_path, monkeypatch, rid)

    def boom(home_, record_ids):
        raise RuntimeError("simulated recompile crash")

    monkeypatch.setattr(verbs, "post_run_recompile", boom)
    result = steward.run(home)

    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"  # positive control
    (row,) = _journal_rows(home, "recompile-failed")
    assert row["records"] == [rid] and "simulated recompile crash" in row["error"]
    assert result.recompile_skipped == []


def test_a_run_that_routed_nothing_runs_no_recompile(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000004")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(lambda ids: [(rid, [rid], [{"id": rid, "verb": "reject"}], "reject", "reject")]),
    )
    calls = []
    monkeypatch.setattr(verbs, "post_run_recompile", lambda h, ids: calls.append(ids))

    result = steward.run(home)

    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"  # positive control
    assert calls == []


# ------------------------------------------------------------ overseer


def test_the_overseer_recompiles_a_refused_route_after_its_run(tmp_path, monkeypatch):
    """The same for the overseer: a decided successor routes a parked
    lesson; its host commit is refused once; the post-run recompile, after
    phase B has let go of the commit lock, lands it."""
    from self_learn import cases
    from self_learn.overseer import run as overseer_run
    from test_failstate_overseer import _ok, _phase_a, _phase_b_common
    from test_overseer_run import _dump, _enabled

    env = make_env(tmp_path)
    home = env.ledger
    _enabled(monkeypatch)
    rid = _seed(home, "lrn-f0000005")
    parked_path = tmp_path / "parked.yaml"
    _dump(parked_path, {
        "kind": "parked", "trigger": "nightly", "outcome": "parked",
        "records": [rid], "scope": "skill:s", "question": "route this?",
        "parked_for": "overseer", "parked_reason": "authority-unclear",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
        "decision": {"verb": "parked", "because": "delegated", "confidence": "provisional"},
    })
    parked = cases.record(home, parked_path, actor="steward")

    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _phase_a(stage)
        else:
            _phase_b_common(stage)
            _dump(stage / "case-r.yaml", {
                "kind": "resolution", "trigger": "weekly", "outcome": "route",
                "records": [rid], "scope": "skill:s", "question": "route?",
                "supersedes": parked,
                "evidence": [{"ref": f"record:{rid}", "quote": "status: pending"}],
                "decision": {"verb": "route", "because": "it holds", "confidence": "settled"},
            })
            _dump(stage / "sheet-r.yaml", {
                "version": 1, "items": [{"id": rid, "verb": "route", "dest": "skill-md"}],
            })
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    _refusing_hook(tmp_path, env.host, times=1)
    skill_md = env.skill_dir / "SKILL.md"

    result = overseer_run.run(home, no_push=True)

    assert Record.from_path(home / "skills/s/resolved" / f"{rid}.md").status == "routed"
    assert (tmp_path / "refusals").read_text().strip() == "1"  # the route's commit was refused
    assert rid in skill_md.read_text()
    assert _status(env.host) == ""
    assert result.recompile_skipped == ()
    rows = [
        json.loads(line)
        for line in overseer_run.journal_path(home).read_text().splitlines()
        if '"recompile"' in line
    ]
    assert [(row["run"], row["records"], row["changed"]) for row in rows] == [
        (result.run, [rid], [str(skill_md)])
    ]
