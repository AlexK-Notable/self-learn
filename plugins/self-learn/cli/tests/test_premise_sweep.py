"""premise_sweep.py (premise-check design, unit U2, plus the sweep half of unit
U8; S-NEXT-u2-sweep): the daily sweep, the cache, two-sweep change detection,
`unavailable` handling, refresh, the read verb, the doctor/selftest row, the
`premises.enabled` setting and the `serve` job.

Nothing here runs a real `systemctl`, `pacman` or `git` for a probe: written
probes are `path` probes on a file in `tmp_path`, or `systemd-show` probes
through an injected command runner that records its argv. No model is ever
called. The sweep's days are simulated by passing `now=`.

Test names avoid the words the credential-path rule refuses (a test's
`tmp_path` directory is named after it, and a file probe under a refused
component is `unavailable` by design).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import (
    cli,
    compiled,
    intents,
    premise_sweep,
    premises,
    reachability,
    selfcheck,
    serve,
    settings,
    steward,
    steward_inputs,
)
from self_learn.compilers import compile_managed_file
from self_learn.hosts import host_slug
from self_learn.ledger import Bucket
from self_learn.premise_sweep import Movement
from self_learn.premises import CommandResult, ProbeEnv
from self_learn.records import Record
from support import commit_all, git, make_behavior, make_env, make_home

DAY = 24 * 3600
T0 = datetime(2026, 10, 31, 3, 30, tzinfo=timezone.utc).timestamp()
BASELINE_AT = "2026-09-22T06:24:50Z"
A, B, C = "lrn-0000a001", "lrn-0000a002", "lrn-0000a003"


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Only the shared temporary ROOT may excuse a test: a refused word in a
    # test's own directory name is a test-naming defect and must fail.
    root = os.path.realpath(tmp_path.parent)
    if premises.credential_path_problem(root, reads_content=True) is not None:
        pytest.skip(f"the temporary root {root} sits under a path premises refuse")
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return e


class Runner:
    """An injected command runner: a fixed answer, every argv recorded."""

    def __init__(self) -> None:
        self.out = b""
        self.rc = 0
        self.times_out = False
        self.calls: list[list[str]] = []

    def __call__(self, argv, env, timeout):
        self.calls.append(list(argv))
        if self.times_out:
            raise subprocess.TimeoutExpired(argv, timeout)
        return CommandResult(self.rc, self.out, b"")


class Sweeper:
    """Runs the sweep on simulated days and reads what it confirmed."""

    def __init__(self, env, tmp_path):
        self.env = env
        self.cache = tmp_path / "cache"
        self.runner = Runner()
        self.claude = tmp_path / "no-claude-dir"
        self.probe_home = tmp_path / "probe-home"
        self.probe_home.mkdir()
        self.day = 0

    def probe_env(self) -> ProbeEnv:
        return ProbeEnv(
            home=self.probe_home, path_env="/nonexistent-bin", runner=self.runner,
            runtime_dir="/nonexistent-runtime-dir",
        )

    def sweep(self, **kw):
        self.day += 1
        return premise_sweep.run(
            self.env.ledger, self.cache, now=T0 + self.day * DAY, env=self.probe_env(),
            claude_dir=self.claude, **kw,
        )

    def moves(self, premise: str | None = None) -> list[Movement]:
        rows = premise_sweep.confirmed_moves(self.env.ledger, self.cache)
        return [m for m in rows if premise is None or m.premise_id == premise]

    def history(self):
        return premise_sweep.read_history(self.cache)


@pytest.fixture
def sw(env, tmp_path) -> Sweeper:
    return Sweeper(env, tmp_path)


def seed(env, rid, premise_list=None, *, routed_at="2026-09-22T06:24:50Z") -> Path:
    """A live routed skill-md lesson in the sandbox ledger (committed)."""
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record = make_behavior(scope="skill:s", record_id=rid)
    record.set_routing({"routed_at": routed_at, "destination": "skill-md", "by": "human"})
    record.set_status("routed")
    if premise_list is not None:
        record.set_premises(premise_list)
    path = resolved / f"{rid}.md"
    record.write(path)
    commit_all(env.ledger, f"seed {rid}")
    return path


def file_premise(watched: Path, **extra) -> dict:
    out = {"id": "p1", "claim": "the watched file exists", "probe": {"kind": "path", "path": str(watched)}}
    out.update(extra)
    return out


SYSTEMD = {"kind": "systemd-show", "scope": "user", "unit": "oo7-daemon.service", "property": "BindsTo"}


def systemd_premise(**extra) -> dict:
    out = {
        "id": "p1", "claim": "the daemon is not bound to the session bus", "probe": dict(SYSTEMD),
        "holds_if": "absent", "match": "dbus-broker.service", "on_change": "re-decide",
    }
    out.update(extra)
    return out


def with_baseline(premise: dict, sw: Sweeper, *, at: str = BASELINE_AT) -> dict:
    """The premise with the baseline the steward's runner would record now."""
    obs = premises.observe(premise, sw.probe_env())
    assert obs is not None and obs.state == premises.OBS_OK, obs
    out = dict(premise)
    out["baseline"] = {**premises.make_baseline(obs), "observed_at": at}
    return out


def reload_premises(path: Path) -> list[dict]:
    return Record.from_path(path).premises or []


def write_config(env, text: str) -> None:
    (env.ledger / "config.yaml").write_text(text, encoding="utf-8")
    commit_all(env.ledger, "config")


def fake_reach(monkeypatch, env, ids, **fields):
    """Replace the reachability instrument with fixed verdicts; the returned
    dict is read afresh on every call, so a test can change it between sweeps."""
    knobs = {
        "state": "reachable", "reason": "registered", "destination": "skill-md",
        "target": str(env.skill_md.resolve()), "detail": "", **fields,
    }

    def rows(home, claude_dir, **kw):
        return [
            reachability.Verdict(
                record_id=i, bucket="skills/s", scope="skill", destination=knobs["destination"],
                variant=None, target=knobs["target"], state=knobs["state"],
                reason=knobs["reason"], detail=knobs["detail"],
            )
            for i in ids
        ]

    monkeypatch.setattr(reachability, "reachability_rows", rows)
    return knobs


# ====================================================== the setting (tier C)


class TestTheSwitch:
    def test_it_is_a_tier_c_switch_that_defaults_to_on(self, env):
        setting = settings.by_name("premises.enabled")
        assert setting.default is True
        assert setting.tier == "C"
        assert setting.env_var is None
        assert premise_sweep.enabled(env.ledger) is True  # control: nothing written, still on

    def test_an_exported_override_cannot_switch_it(self, env, monkeypatch):
        """The process override channel is closed for a switch that is the
        person's: an agent exports `SELF_LEARN_OVERRIDE_*` for read verbs
        routinely."""
        assert settings.by_name("premises.enabled").override_channel is False
        monkeypatch.setenv("SELF_LEARN_OVERRIDE_PREMISES_ENABLED", "0")
        assert premise_sweep.enabled(env.ledger) is True

    def test_an_agent_shell_cannot_set_it(self, env, monkeypatch):
        monkeypatch.setenv("CODEX_THREAD_ID", "synthetic")
        with pytest.raises(settings.AgentSettingRefusal):
            settings.config_set(env.ledger, "premises.enabled", "0")
        assert premise_sweep.enabled(env.ledger) is True

    def test_set_false_in_the_config_it_stops_the_sweep_and_the_due_check(self, env, sw):
        seed(env, A)
        assert premise_sweep.is_due(env.ledger, sw.cache, T0) is True  # control: on, due
        write_config(env, "premises:\n  enabled: false\n")
        assert premise_sweep.enabled(env.ledger) is False
        assert premise_sweep.is_due(env.ledger, sw.cache, T0) is False
        result = sw.sweep()
        assert result.status == "disabled"
        assert not premise_sweep.observations_path(sw.cache).exists()
        assert not premise_sweep.state_path(sw.cache).exists()

    def test_the_read_verb_works_with_the_switch_off(self, env, sw):
        write_config(env, "premises:\n  enabled: false\n")
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [with_baseline(file_premise(watched), sw)])
        rows = premise_sweep.check(env.ledger, record_id=A, cache_dir=sw.cache, env=sw.probe_env(), claude_dir=sw.claude)
        assert [r.verdict for r in rows if r.premise_id == "p1"] == ["holds"]


# ================================================================ due checks


class TestDue:
    def test_it_needs_a_resolved_lesson_and_waits_a_day(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        env = make_env(tmp_path)
        sweeper = Sweeper(env, tmp_path)
        assert premise_sweep.is_due(env.ledger, sweeper.cache, T0) is False  # nothing resolved
        seed(env, A)
        assert premise_sweep.is_due(env.ledger, sweeper.cache, T0) is True  # control
        result = sweeper.sweep()
        assert result.status == "ok"
        at = T0 + DAY
        assert premise_sweep.is_due(env.ledger, sweeper.cache, at + 23 * 3600) is False
        assert premise_sweep.is_due(env.ledger, sweeper.cache, at + 25 * 3600) is True

    def test_a_missing_home_is_not_due_and_does_not_raise(self, tmp_path):
        assert premise_sweep.is_due(tmp_path / "no-such-home", tmp_path / "cache", T0) is False

    def test_a_second_run_within_hours_is_not_a_new_sweep(self, env, sw):
        seed(env, A)
        assert sw.sweep().status == "ok"
        before = premise_sweep.observations_path(sw.cache).read_text(encoding="utf-8")
        again = premise_sweep.run(
            env.ledger, sw.cache, now=T0 + DAY + 3600, env=sw.probe_env(), claude_dir=sw.claude
        )
        assert again.status == "too-soon"
        assert premise_sweep.observations_path(sw.cache).read_text(encoding="utf-8") == before

    def test_a_future_dated_marker_does_not_hold_the_sweep_off(self, env, sw):
        """S-68's failure for the other jobs: a stamp from a clock that was
        wrong once must not keep the job away until that date."""
        seed(env, A)
        premise_sweep._store_state(sw.cache, {"last_attempt_at": "2099-01-01T00:00:00Z"})
        assert premise_sweep.is_due(env.ledger, sw.cache, T0) is True
        result = premise_sweep.run(env.ledger, sw.cache, now=T0, env=sw.probe_env(), claude_dir=sw.claude)
        assert result.status == "ok"
        marker = premise_sweep.read_state(sw.cache)["last_attempt_at"]
        assert marker.startswith("2026-10-31")  # rewritten with the real time
        assert premise_sweep.is_due(env.ledger, sw.cache, T0 + 3600) is False  # control: now it waits its day

    def test_a_sweep_that_dies_still_leaves_its_attempt_marker(self, env, sw, monkeypatch):
        """Else a sweep that crashes would be due again on the very next tick."""
        seed(env, A)

        def boom(*a, **k):
            raise RuntimeError("synthetic crash")

        monkeypatch.setattr(premise_sweep, "_store_history", boom)
        with pytest.raises(RuntimeError):
            sw.sweep()
        assert premise_sweep.is_due(env.ledger, sw.cache, T0 + DAY + 3600) is False
        assert premise_sweep.read_state(sw.cache)["last_status"] == "running"


# ====================================================== change detection


class TestTwoSweepDetection:
    def test_a_moved_value_counts_only_on_the_second_sweep_in_a_row(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched), sw)])

        sw.sweep()
        assert sw.moves() == []  # control: it holds
        watched.unlink()
        sw.sweep()
        assert sw.moves() == []  # first sight: not yet
        sw.sweep()
        (move,) = sw.moves("p1")
        assert (move.record_id, move.kind, move.shown) == (A, "probe", "missing")
        assert move.baseline_shown == "file"
        assert move.since < move.observed_at
        # the record itself was not touched: the sweep decides nothing
        assert reload_premises(path)[0]["baseline"]["shown"] == "file"

    def test_a_value_that_flaps_never_confirms(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [with_baseline(file_premise(watched), sw)])
        for present in (True, False, True, False, True):
            if present:
                watched.write_text("x", encoding="utf-8")
            elif watched.exists():
                watched.unlink()
            sw.sweep()
            assert sw.moves("p1") == []
        # control: the same value twice in a row does confirm
        watched.unlink()
        sw.sweep()
        sw.sweep()
        assert len(sw.moves("p1")) == 1

    def test_the_two_observations_must_agree(self, env, sw):
        """Moved on two sweeps, but to two different values: not stable."""
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.sweep()
        sw.runner.out = b"dbus-broker.service\n"
        sw.sweep()
        sw.runner.out = b"dbus-broker.service other.service\n"
        sw.sweep()
        assert sw.moves("p1") == []
        sw.sweep()  # control: the same changed value again
        assert len(sw.moves("p1")) == 1

    def test_a_ledger_probe_counts_on_first_sight(self, env, sw):
        other = seed(env, B)
        premise = {"id": "p1", "claim": "the lesson it leans on stays placed", "probe": {"kind": "ledger", "ref": B}}
        premise = with_baseline_ledger(premise, sw, env)
        seed(env, A, [premise])
        sw.sweep()
        assert sw.moves("p1") == []  # control: B is still routed
        other.unlink()
        sw.sweep()
        (move,) = sw.moves("p1")
        assert move.kind == "ledger"

    def test_a_baseline_that_already_contradicts_counts_from_the_next_sweep(self, env, sw):
        sw.runner.out = b"dbus-broker.service\n"  # the claim is false from the start
        premise = with_baseline(systemd_premise(), sw, at="2026-10-31T03:30:00Z")  # T0: written the night before the sweep
        assert premise["baseline"]["state"] == "contradicts-claim"
        seed(env, A, [premise])
        sw.sweep()  # one sweep after the baseline was written
        assert len(sw.moves("p1")) == 1

    def test_a_baseline_that_contradicts_does_not_count_on_the_sweep_of_the_same_day(self, env, sw):
        sw.runner.out = b"dbus-broker.service\n"
        # written at 01:00 on the day of the first sweep (03:30): the steward counts it
        # only from the next calendar day, so the sweep must not count it earlier
        premise = with_baseline(systemd_premise(), sw, at="2026-11-01T01:00:00Z")
        assert premise["baseline"]["state"] == "contradicts-claim"
        seed(env, A, [premise])
        sw.sweep()
        assert sw.moves("p1") == []  # same day: the ordinary two-sweep rule applies
        sw.sweep()
        assert len(sw.moves("p1")) == 1  # control: the same value on a second sweep counts

    def test_a_probe_rewritten_by_the_steward_forgets_the_old_observations(self, env, sw):
        path = seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.runner.out = b"dbus-broker.service\n"
        sw.sweep()
        sw.sweep()
        assert len(sw.moves("p1")) == 1  # control: confirmed under the old question
        record = Record.from_path(path)
        new = systemd_premise(claim="the daemon is bound to the session bus", holds_if="present")
        record.set_premises([with_baseline(new, sw)])
        record.write(path)
        assert sw.moves("p1") == []  # the old rows answer another question
        sw.sweep()
        assert sw.moves("p1") == []

    def test_behavioural_premises_are_never_observed(self, env, sw):
        seed(env, A, [{"id": "p1", "claim": "it can outlive a bus restart", "probe": None}])
        sw.sweep()
        assert not any(key[1] == "p1" for key in sw.history())

    def test_the_sweep_only_runs_the_catalogs_read_only_commands(self, env, sw):
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.runner.calls.clear()
        sw.sweep()
        assert sw.runner.calls, "control: the probe did run"
        for argv in sw.runner.calls:
            assert argv[0] == "systemctl" and argv[2] == "show"


class TestAFailedNightKeepsTheHistory:
    def test_a_lesson_that_did_not_parse_keeps_its_earlier_rows(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched), sw)])
        original = path.read_bytes()
        watched.unlink()
        sw.sweep()
        before = sw.history()[(A, "p1")]
        assert len(before) == 1  # control: there is a reading to lose
        path.write_text("not a record at all\n", encoding="utf-8")
        result = sw.sweep()
        assert any("did not parse" in e for e in result.errors)
        assert sw.history()[(A, "p1")] == before
        path.write_bytes(original)
        sw.sweep()
        assert len(sw.history()[(A, "p1")]) == 2

    def test_probes_that_raise_are_written_down_as_unavailable_and_the_history_stays(self, env, sw, monkeypatch):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [with_baseline(file_premise(watched), sw)])
        sw.sweep()

        def boom(*a, **k):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(premise_sweep, "_written_rows", boom)
        result = sw.sweep()
        assert any("probes failed" in e for e in result.errors)
        rows = sw.history()[(A, "p1")]
        assert [r["state"] for r in rows] == ["ok", "unavailable"]

    def test_a_lesson_re_homed_away_from_a_failing_placement_stops_being_reported(self, env, sw, monkeypatch):
        path = seed(env, A)
        fake_reach(monkeypatch, env, [A], state="unreachable", reason="plugin-disabled")
        sw.sweep()
        sw.sweep()
        assert [m.premise_id for m in sw.moves("@reach")] == ["@reach"]  # control: it is failing and counted
        assert (A, "@intact") in sw.history()  # control: a managed-region lesson has the third premise too
        rows = {r.name: r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + 2 * DAY)}
        assert f"{A}@reach" in rows["placement-failing"].detail
        # the steward re-homes it to a hook: no managed region any more, so no @intact row
        record = Record.from_path(path)
        record.set_routing({"routed_at": "2026-09-22T06:24:50Z", "destination": "hook", "by": "human"})
        record.write(path)
        fake_reach(monkeypatch, env, [A], destination="hook", state="reachable", reason="registered")
        sw.sweep()
        history = sw.history()
        assert (A, "@intact") not in history  # its old reading is not the last word
        assert history[(A, "@reach")][-1]["failing"] is False  # control: the premise it still has is measured afresh
        # and then to `reference`, which is outside the reachability domain: nothing is measured
        record = Record.from_path(path)
        record.set_routing({"routed_at": "2026-09-22T06:24:50Z", "destination": "reference", "by": "human"})
        record.write(path)
        fake_reach(monkeypatch, env, [])
        sw.sweep()
        assert not any(key[0] == A and key[1].startswith("@") for key in sw.history())
        assert sw.moves("@reach") == [] and sw.moves("@writable") == []
        rows = {r.name: r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + 4 * DAY)}
        assert "placement-failing" not in rows

    def test_a_premise_taken_off_a_lesson_drops_its_rows_while_its_other_rows_stay(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        keep = file_premise(watched)
        gone = file_premise(watched, id="p2")
        path = seed(env, A, [with_baseline(keep, sw), with_baseline(gone, sw)])
        sw.sweep()
        assert {(A, "p1"), (A, "p2")} <= set(sw.history())  # control: both were read
        record = Record.from_path(path)
        record.set_premises([with_baseline(keep, sw)])
        record.write(path)
        sw.sweep()
        history = sw.history()
        assert (A, "p2") not in history
        assert len(history[(A, "p1")]) == 2

    def test_when_reachability_cannot_be_measured_a_failing_placement_stops_counting(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A], state="unreachable", reason="plugin-disabled")
        sw.sweep()
        sw.sweep()
        assert [m.premise_id for m in sw.moves("@reach")] == ["@reach"]  # control: counted

        def broken(*a, **k):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(reachability, "reachability_rows", broken)
        sw.sweep()
        assert sw.moves("@reach") == []  # last night's failure is not carried as today's
        history = sw.history()
        assert history[(A, "@reach")][-1]["state"] == "unavailable"
        # the region premise too: and it says WHY, which an @intact that was
        # merely "no compile record yet" on the earlier nights would not
        intact = history[(A, "@intact")][-1]
        assert intact["state"] == "unavailable" and "reachability could not be measured" in intact["reason"]


class TestUnavailableNeverCounts:
    def test_it_is_neither_a_confirmation_nor_a_move(self, env, sw):
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.sweep()
        sw.runner.times_out = True
        for _ in range(5):
            sw.sweep()
            assert sw.moves("p1") == []
        rows = sw.history()[(A, "p1")]
        assert [r["state"] for r in rows] == ["unavailable"] * premise_sweep.HISTORY_KEEP

    def test_an_unavailable_sweep_between_two_moved_ones_breaks_the_pair(self, env, sw):
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.runner.out = b"dbus-broker.service\n"
        sw.sweep()  # moved
        sw.runner.times_out = True
        sw.sweep()  # unavailable
        sw.runner.times_out = False
        sw.sweep()  # moved again: only one in a row
        assert sw.moves("p1") == []
        sw.sweep()  # control: now two in a row
        assert len(sw.moves("p1")) == 1

    def test_three_unavailable_sweeps_in_a_row_make_a_broken_probe(self, env, sw, monkeypatch):
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.runner.times_out = True
        for n in range(1, 4):
            sw.sweep()
            warned = [r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + sw.day * DAY) if r.verdict == "WARN"]
            assert bool(warned) == (n == 3), n
        assert f"{A}/p1" in warned[0].detail
        # the selftest row says the same, as a WARN naming the probe
        monkeypatch.setattr(premise_sweep, "default_cache_dir", lambda home: sw.cache)
        verdict, detail = selfcheck._check_premises(env.ledger)
        assert verdict is selfcheck.Verdict.WARN and f"{A}/p1" in detail

    def test_a_probe_that_works_again_clears_the_warning(self, env, sw):
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.runner.times_out = True
        for _ in range(3):
            sw.sweep()
        sw.runner.times_out = False
        sw.sweep()
        rows = premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + sw.day * DAY)
        assert not [r for r in rows if r.verdict == "WARN"]


def with_baseline_ledger(premise, sw, env):
    """A baseline for a `ledger` probe: its value read from this ledger."""
    probe_env = ProbeEnv(home=sw.probe_home, ledger_home=env.ledger)
    obs = premises.observe(premise, probe_env)
    assert obs is not None and obs.state == premises.OBS_OK, obs
    out = dict(premise)
    out["baseline"] = {**premises.make_baseline(obs), "observed_at": BASELINE_AT}
    return out


class TestOlderThanTheBaseline:
    def test_an_observation_from_before_the_baseline_never_counts(self, env, sw):
        """The steward re-records a baseline from an apply-time probe that
        flapped ("file" again, for a moment). The reading of the night before,
        made against the old baseline, must not pair with the next night's:
        two sweeps in a row means two made AFTER the baseline."""
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched), sw)])
        sw.sweep()
        watched.unlink()
        sw.sweep()  # day 2: "missing", first sight
        assert sw.moves("p1") == []
        # the re-recorded baseline says "file", written between day 2 and day 3
        watched.write_text("x", encoding="utf-8")
        again = with_baseline(file_premise(watched), sw, at="2026-11-02T12:00:00Z")
        watched.unlink()
        record = Record.from_path(path)
        record.set_premises([again])
        record.write(path)
        sw.sweep()  # day 3: "missing" again, the first made after the baseline
        assert sw.moves("p1") == []  # not confirmed by the day-2 reading
        sw.sweep()  # control: day 4 is the second after the baseline
        assert len(sw.moves("p1")) == 1


# ====================================================================== cache


class TestTheSeamWithTheSteward:
    """The steward reads what this cache file holds through
    `steward_inputs.moved_premises`, which asks `premise_sweep.confirmed_moves`
    (U4 removed its own reader, `steward_inputs.read_observations`). A key
    renamed on one side makes a confirmed probe move silently stop reaching
    the steward, and no test of either side alone would notice."""

    def _moved_two_sweeps(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched), sw)])
        watched.unlink()
        sw.sweep()
        sw.sweep()
        return path

    def test_every_line_has_the_keys_the_steward_reads(self, env, sw):
        self._moved_two_sweeps(env, sw)
        raw = premise_sweep.observations_path(sw.cache).read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in raw]
        assert any(r["record"] == A and r["premise"] == "p1" for r in rows)  # control: a probe row is there
        for row in rows:
            assert {"record", "premise", "state", "value_sha", "shown", "claim", "reason", "observed_at"} <= set(row)
            assert row["record"].startswith("lrn-")
            assert datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))

    def test_the_steward_reader_reads_what_the_sweep_wrote(self, env, sw):
        """Integration 2026-10-31: this test used to skip whenever
        `steward_inputs.read_observations` was missing, and U4 removed that
        reader, so on the combined branch it could only skip. It now reads
        the seam the steward really uses, from the cache the sweep wrote."""
        self._moved_two_sweeps(env, sw)
        found = steward_inputs.moved_premises(
            env.ledger, history=premise_sweep.read_history(sw.cache)
        )
        assert A in found, found  # the steward sees the move the sweep confirmed
        (item,) = found[A].items
        assert item["premise"] == "p1" and item["how"] == "probe"
        assert item["now"] == "missing"
        assert len(sw.moves("p1")) == 1  # both sides call it confirmed

class TestCache:
    def test_it_keeps_the_last_three_observations_per_premise(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [with_baseline(file_premise(watched), sw)])
        for _ in range(5):
            sw.sweep()
        rows = sw.history()[(A, "p1")]
        assert len(rows) == premise_sweep.HISTORY_KEEP == 3
        assert [r["sweep"] for r in rows] == sorted(r["sweep"] for r in rows)
        assert rows[-1]["sweep"].startswith("2026-11-05")  # day 5

    def test_a_lost_cache_costs_a_day_and_changes_nothing_on_the_record(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched), sw)])
        before = path.read_bytes()
        watched.unlink()
        sw.sweep()
        sw.sweep()
        assert len(sw.moves("p1")) == 1
        premise_sweep.observations_path(sw.cache).unlink()
        assert sw.moves("p1") == []  # nothing triggers from nothing
        sw.sweep()
        assert sw.moves("p1") == []  # and the first sight after the loss is only a first sight
        assert path.read_bytes() == before

    def test_a_damaged_cache_line_is_skipped_not_fatal(self, env, sw):
        seed(env, A)
        sw.sweep()
        obs = premise_sweep.observations_path(sw.cache)
        obs.write_text("{not json\n[]\n" + obs.read_text(encoding="utf-8"), encoding="utf-8")
        assert sw.history()  # still read
        assert sw.sweep().status == "ok"

    def test_the_sweep_writes_only_its_cache_folder_unless_it_refreshes(self, env, sw):
        seed(env, A, [{"id": "p1", "claim": "it can outlive a bus restart", "probe": None}])
        head = git(env.ledger, "rev-parse", "HEAD").stdout
        sw.sweep()
        assert git(env.ledger, "rev-parse", "HEAD").stdout == head
        assert git(env.ledger, "status", "--porcelain").stdout == ""
        assert {p.name for p in (sw.cache / "premises").iterdir()} == {"observations.jsonl", "sweep.json"}


# ==================================================================== refresh


class TestRefresh:
    def test_a_refresh_premise_is_rebaselined_by_code_in_one_commit(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched, on_change="refresh"), sw)])
        sw.sweep()
        head = git(env.ledger, "rev-parse", "HEAD").stdout
        watched.unlink()
        first = sw.sweep()
        assert first.refreshed == []  # first sight: nothing yet
        assert git(env.ledger, "rev-parse", "HEAD").stdout == head
        second = sw.sweep()
        assert second.refreshed == [f"{A}/p1"]
        subject = git(env.ledger, "log", "-1", "--format=%s").stdout.strip()
        assert subject == f"self-learn: premises refresh {A} p1"
        body = git(env.ledger, "log", "-1", "--format=%b").stdout
        assert "file -> missing" in body and "no model call" in body
        assert git(env.ledger, "show", "--name-only", "--format=", "HEAD").stdout.split() == [
            path.relative_to(env.ledger).as_posix()
        ]
        (premise,) = reload_premises(path)
        assert premise["baseline"]["shown"] == "missing"
        assert premise["claim"] == "the watched file exists"  # nothing else changed
        # it never reaches the steward, and a third sweep writes nothing more
        assert sw.moves("p1") == []
        after = git(env.ledger, "rev-parse", "HEAD").stdout
        assert sw.sweep().refreshed == []
        assert git(env.ledger, "rev-parse", "HEAD").stdout == after

    def test_a_re_decide_premise_is_never_rebaselined_by_code(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path = seed(env, A, [with_baseline(file_premise(watched, on_change="re-decide"), sw)])
        head = git(env.ledger, "rev-parse", "HEAD").stdout
        sw.sweep()
        watched.unlink()
        sw.sweep()
        assert sw.sweep().refreshed == []
        assert git(env.ledger, "rev-parse", "HEAD").stdout == head
        assert reload_premises(path)[0]["baseline"]["shown"] == "file"
        assert len(sw.moves("p1")) == 1

    def test_a_lesson_that_changed_meanwhile_is_not_rebaselined_under_the_lock(self, env, sw):
        """The record is read again inside the lock: an update made from rows
        observed under the OLD question is refused once the steward has
        rewritten the probe. B is the positive control: the same call, with
        nothing changed meanwhile, writes."""
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        path_a = seed(env, A, [with_baseline(file_premise(watched, on_change="refresh"), sw)])
        path_b = seed(env, B, [with_baseline(file_premise(watched, on_change="refresh"), sw)])
        sw.sweep()
        watched.unlink()
        sw.sweep()  # first sight only: the sweep itself writes nothing yet
        stale_a = [sw.history()[(A, "p1")][-1]]
        stale_b = [sw.history()[(B, "p1")][-1]]
        record = Record.from_path(path_a)
        # The steward's new question has a baseline of its OWN that differs from
        # the stale reading ("missing"): its file exists. So the only thing that
        # can refuse the stale update is the same-question check, not the
        # equal-baseline clause (a missing file here would make both refuse).
        elsewhere = sw.probe_home / "elsewhere.txt"
        elsewhere.write_text("y", encoding="utf-8")
        other = file_premise(elsewhere, on_change="refresh")
        record.set_premises([with_baseline(other, sw)])
        record.write(path_a)
        commit_all(env.ledger, "steward rewrote A's probe")
        head = git(env.ledger, "rev-parse", "HEAD").stdout
        assert premise_sweep._refresh_record(env.ledger, A, stale_a) is None
        assert git(env.ledger, "rev-parse", "HEAD").stdout == head
        assert reload_premises(path_a)[0]["probe"]["path"].endswith("elsewhere.txt")
        assert reload_premises(path_a)[0]["baseline"]["shown"] == "file"  # not overwritten with "missing"
        assert premise_sweep._refresh_record(env.ledger, B, stale_b) == "p1"  # control
        assert git(env.ledger, "rev-parse", "HEAD").stdout != head
        assert reload_premises(path_b)[0]["baseline"]["shown"] == "missing"

    def test_a_refresh_refused_by_a_stopped_intent_is_named_for_serve(self, env, sw, monkeypatch):
        """02 7.2a.7: the intent id must reach serve's own output, not only
        sweep.json."""
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [with_baseline(file_premise(watched, on_change="refresh"), sw)])
        sw.sweep()
        watched.unlink()
        sw.sweep()
        stopped = intents.RecoverResult()
        stopped._stop("int-synthetic", "a half-written ledger write")

        def refuse(*a, **k):
            raise intents.LedgerStoppedError(stopped)

        monkeypatch.setattr(premise_sweep, "_refresh_record", refuse)
        result = sw.sweep()
        assert result.stopped == ["int-synthetic: a half-written ledger write"]
        assert any("the ledger is stopped" in e for e in result.errors)
        assert result.refreshed == []

    def test_a_failed_refresh_is_recorded_and_the_sweep_carries_on(self, env, sw, monkeypatch):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [with_baseline(file_premise(watched, on_change="refresh"), sw)])
        sw.sweep()
        watched.unlink()
        sw.sweep()

        def boom(*a, **k):
            raise OSError("synthetic disk failure")

        monkeypatch.setattr(premise_sweep, "_refresh_record", boom)
        result = sw.sweep()
        assert result.status == "ok"
        assert any("refresh failed" in e for e in result.errors)
        assert premise_sweep.read_state(sw.cache)["last_status"] == "ok"


# ====================================================== placement premises


class TestReach:
    def test_unreachable_counts_after_two_sweeps(self, env, sw, monkeypatch):
        seed(env, A)
        knobs = fake_reach(monkeypatch, env, [A])
        sw.sweep()
        assert sw.moves("@reach") == []  # control: reachable
        knobs.update(state="unreachable", reason="plugin-disabled", detail="the plugin is switched off")
        sw.sweep()
        assert sw.moves("@reach") == []
        sw.sweep()
        (move,) = sw.moves("@reach")
        assert move.kind == "placement" and move.record_id == A
        assert "plugin-disabled" in move.shown and move.group is None
        assert move.detail == "the plugin is switched off"

    def test_unmeasurable_never_counts(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A], state="unmeasurable", reason="claude-dir-absent")
        for _ in range(4):
            sw.sweep()
        assert sw.moves("@reach") == []
        rows = sw.history()[(A, "@reach")]
        assert rows[-1]["state"] == "unavailable" and rows[-1]["value_sha"] is None

    def test_a_hook_waiting_for_the_switch_holds(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A], destination="hook", state="unreachable", reason="not-registered")
        sw.sweep()
        sw.sweep()
        assert sw.moves("@reach") == []  # overseer.hook_activation is off: it waits for a person
        write_config(env, "overseer:\n  hook_activation: true\n")
        sw.sweep()
        sw.sweep()
        assert [m.premise_id for m in sw.moves("@reach")] == ["@reach"]  # control: with the switch on it fails

    def test_a_different_failure_is_a_new_value_and_restarts_the_count(self, env, sw, monkeypatch):
        seed(env, A)
        knobs = fake_reach(monkeypatch, env, [A], state="unreachable", reason="plugin-disabled")
        sw.sweep()
        knobs.update(reason="not-installed")
        sw.sweep()
        assert sw.moves("@reach") == []
        sw.sweep()
        assert len(sw.moves("@reach")) == 1


class TestWritable:
    def _plain_root(self, env):
        (env.ledger / "hosts.yaml").write_text(
            f"skills_root:\n  path: {env.host}\n  mode: plain\nprojects: []\n", encoding="utf-8"
        )

    def test_a_tracked_file_in_a_plain_host_fails_on_two_sweeps(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A])
        self._plain_root(env)
        sw.sweep()
        assert sw.moves("@writable") == []
        sw.sweep()
        (move,) = sw.moves("@writable")
        assert "tracked by git" in move.detail and move.record_id == A

    def test_the_same_file_in_a_git_host_holds(self, env, sw, monkeypatch):
        """The positive control: the identical target, the host in git mode."""
        seed(env, A)
        fake_reach(monkeypatch, env, [A])
        sw.sweep()
        sw.sweep()
        assert sw.moves("@writable") == []
        assert sw.history()[(A, "@writable")][-1]["shown"] == "git-mode host"

    def test_a_user_lesson_is_placed_under_the_sandbox_claude_dir_not_the_operators(self, env, sw):
        """N-8: the user-scope host is the directory of the CLAUDE.md the
        sweep was told about; without the override it would be the real
        ~/.claude and the check would read the operator's machine."""
        bucket = Bucket(path=env.ledger / "user", scope="user", name="user")
        record = make_behavior(scope="user", record_id=A)
        verdict = reachability.Verdict(
            record_id=A, bucket="user", scope="user", destination="claude-md", variant=None,
            target=str(sw.claude / "CLAUDE.md"), state="reachable", reason="registered", detail="",
        )
        assert premise_sweep._host_for(env.ledger, bucket, record, verdict, sw.claude) == (sw.claude, "plain")

    def test_a_project_lesson_is_placed_in_its_registered_project_host(self, env, sw):
        project = env.ledger / "projects" / "p"
        project.mkdir(parents=True)
        bucket = Bucket(path=project, scope="project", name="p")
        record = make_behavior(scope="project", record_id=A)
        verdict = reachability.Verdict(
            record_id=A, bucket="projects/p", scope="project", destination="claude-md", variant=None,
            target=str(env.host / "CLAUDE.md"), state="reachable", reason="registered", detail="",
        )
        # no project path is recorded for this bucket: unresolved, said so, not a crash
        assert premise_sweep._host_for(env.ledger, bucket, record, verdict, sw.claude) is None
        fact = premise_sweep._writable_fact(env.ledger, bucket, record, verdict, sw.claude)
        assert fact.state == "unavailable" and "not registered" in fact.detail
        # control: once the bucket records its project path, the host resolves
        (project / "meta.yaml").write_text(f"path: {env.host}\n", encoding="utf-8")
        assert premise_sweep._host_for(env.ledger, bucket, record, verdict, sw.claude) == (env.host, "git")
        assert premise_sweep._writable_fact(env.ledger, bucket, record, verdict, sw.claude).state == "holds"

    def test_an_unresolved_target_is_unavailable_not_failing(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A], target="")
        self._plain_root(env)
        for _ in range(3):
            sw.sweep()
        assert sw.moves("@writable") == []
        assert sw.history()[(A, "@writable")][-1]["state"] == "unavailable"


class TestIntact:
    def _compile_two(self, env):
        a = Record.from_path(seed(env, A, routed_at="2026-09-22T06:24:50Z"))
        b = Record.from_path(seed(env, B, routed_at="2026-09-23T06:24:50Z"))
        compile_managed_file(env.skill_md, [a, b])
        self._write_entry(env)
        return a, b

    def _write_entry(self, env, *, based_on=None):
        region = compiled.region_bytes(env.skill_md.read_text(encoding="utf-8"), "managed")
        assert region is not None
        compiled.write_entry(
            env.ledger, host_slug(env.ledger, env.host, scope_kind="skill"),
            compiled.region_key(env.host, env.skill_md, "managed"),
            region="managed", sha256=compiled.sha256_hex(region), based_on_sha256=based_on,
            nbytes=len(region), by="test", host=str(env.host), mode="git",
        )

    def _edit(self, env, fn):
        lines = env.skill_md.read_text(encoding="utf-8").split("\n")
        env.skill_md.write_text("\n".join(fn(lines)), encoding="utf-8")

    def _two_sweeps(self, sw):
        sw.sweep()
        sw.sweep()

    def test_an_untouched_block_holds(self, env, sw, monkeypatch):
        self._compile_two(env)
        fake_reach(monkeypatch, env, [A, B])
        self._two_sweeps(sw)
        assert sw.moves("@intact") == []
        assert sw.history()[(A, "@intact")][-1]["shown"] == "clean"

    def test_a_stale_block_is_not_a_hand_edit(self, env, sw, monkeypatch):
        """`stale`: the ledger moved and a write never landed; `recompile` repairs it."""
        self._compile_two(env)
        original = compiled.region_bytes(env.skill_md.read_text(encoding="utf-8"), "managed")
        assert original is not None
        self._edit(env, lambda lines: [ln + " (new words)" if f"({B})" in ln else ln for ln in lines])
        self._write_entry(env, based_on=compiled.sha256_hex(original))  # entry says: we last saw the old text
        self._edit(env, lambda lines: [ln.replace(" (new words)", "") for ln in lines])  # disk is the old text again
        fake_reach(monkeypatch, env, [A, B])
        self._two_sweeps(sw)
        assert sw.moves("@intact") == []

    def test_a_hand_edit_lands_on_the_lesson_whose_line_changed(self, env, sw, monkeypatch):
        self._compile_two(env)
        self._edit(env, lambda lines: [ln + " (hand note)" if f"({B})" in ln else ln for ln in lines])
        fake_reach(monkeypatch, env, [A, B])
        sw.sweep()
        assert sw.moves("@intact") == []  # first sight
        sw.sweep()
        (move,) = sw.moves("@intact")
        assert move.record_id == B
        assert move.group == str(env.skill_md.resolve())
        assert "entry line differs" in move.detail
        assert sw.history()[(A, "@intact")][-1]["shown"] == "entry unedited"

    def test_an_edit_that_touches_no_entry_goes_on_the_first_lesson_in_file_order(self, env, sw, monkeypatch):
        self._compile_two(env)
        self._edit(
            env,
            lambda lines: [x for ln in lines for x in ([ln, "- a note somebody added"] if f"({A})" in ln else [ln])],
        )
        fake_reach(monkeypatch, env, [A, B])
        self._two_sweeps(sw)
        (move,) = sw.moves("@intact")
        assert move.record_id == A
        assert "touches no lesson's entry line" in move.detail

    def test_when_the_ledger_has_moved_since_the_write_the_edit_stays_region_level(self, env, sw, monkeypatch):
        """The line comparison is trusted only when the ledger still renders
        the very region the compile record last wrote; otherwise a changed
        lesson would be blamed for a hand edit it never had."""
        self._compile_two(env)
        self._edit(env, lambda lines: [ln + " (hand note)" if f"({B})" in ln else ln for ln in lines])
        a_path = env.ledger / "skills" / "s" / "resolved" / f"{A}.md"
        a_path.write_text(
            a_path.read_text(encoding="utf-8").replace("Stop the container first.", "Stop the container first, then wait."),
            encoding="utf-8",
        )
        assert "then wait" in a_path.read_text(encoding="utf-8")  # control: what the compiler renders for A changed
        fake_reach(monkeypatch, env, [A, B])
        self._two_sweeps(sw)
        (move,) = sw.moves("@intact")
        assert move.record_id == A  # the first lesson in file order, not the edited B
        assert "region-level" in move.detail

    def test_a_missing_block_fails_every_lesson_in_it(self, env, sw, monkeypatch):
        self._compile_two(env)
        env.skill_md.write_text("# the skill, with its managed block removed\n", encoding="utf-8")
        fake_reach(monkeypatch, env, [A, B])
        self._two_sweeps(sw)
        assert sorted(m.record_id for m in sw.moves("@intact")) == [A, B]

    def test_a_region_with_no_compile_record_is_unavailable_not_failing(self, env, sw, monkeypatch):
        a = Record.from_path(seed(env, A))
        compile_managed_file(env.skill_md, [a])  # a region on disk, no compile record entry
        fake_reach(monkeypatch, env, [A])
        for _ in range(3):
            sw.sweep()
        assert sw.moves("@intact") == []
        assert sw.history()[(A, "@intact")][-1]["state"] == "unavailable"


class TestJudging:
    def test_a_placement_row_that_holds_judges_as_holds(self):
        rows = [{"state": "ok", "value_sha": "a" * 32, "failing": False, "observed_at": "t1", "sweep": "t1"}]
        assert premise_sweep.judge_placement(rows).verdict == "holds"

    def test_no_history_is_not_a_verdict(self):
        assert premise_sweep.judge_placement([]).verdict == "no-history"
        assert premise_sweep.judge_probe({"id": "p1", "probe": {"kind": "which", "name": "git"}}, []).verdict == "no-history"


# ======================================================= the oo7 replay


class TestTheOo7Replay:
    """Design §4: a scratch lesson with the oo7 premise's shape (no real ledger
    content), a fake `systemctl` that first prints nothing and then
    `dbus-broker.service`: one confirmed move after the second sweep that sees
    it, and none once the decision re-baselines."""

    def test_one_move_after_the_second_sweep_and_none_after_the_decision(self, env, sw):
        path = seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.sweep()
        assert sw.moves() == []
        sw.runner.out = b"dbus-broker.service\n"
        sw.sweep()
        assert sw.moves() == []
        sw.sweep()
        (move,) = sw.moves("p1")
        assert move.claim == "the daemon is not bound to the session bus"
        assert move.shown == "dbus-broker.service"
        # the steward decides: the claim is rewritten and re-baselined
        record = Record.from_path(path)
        decided = systemd_premise(claim="the daemon is bound to the session bus", holds_if="present")
        record.set_premises([with_baseline(decided, sw)])
        record.write(path)
        assert sw.moves() == []
        sw.sweep()
        sw.sweep()
        assert sw.moves() == []  # control: it does not come back


# ================================================================ read verb


class TestCheck:
    def _moved_lesson(self, env, sw):
        watched = sw.probe_home / "watched.txt"
        watched.write_text("x", encoding="utf-8")
        seed(env, A, [
            with_baseline(file_premise(watched), sw),
            {"id": "p2", "claim": "it can outlive a bus restart", "probe": None},
        ])
        watched.unlink()
        return watched

    def _check(self, env, sw, **kw):
        return premise_sweep.check(
            env.ledger, cache_dir=sw.cache, env=sw.probe_env(), claude_dir=sw.claude,
            now=T0 + 10 * DAY, **kw,
        )

    def test_it_judges_each_premise_against_its_baseline(self, env, sw):
        self._moved_lesson(env, sw)
        rows = {r.premise_id: r for r in self._check(env, sw, record_id=A)}
        assert rows["p1"].verdict == "moved" and rows["p1"].confirmed == "first-sight"
        assert (rows["p1"].baseline_shown, rows["p1"].current_shown) == ("file", "missing")
        assert rows["p2"].verdict == "no-probe" and rows["p2"].kind == "behaviour"
        assert {"@reach", "@writable", "@intact"} <= set(rows)

    def test_it_says_when_the_sweep_would_count_the_move(self, env, sw):
        self._moved_lesson(env, sw)
        sw.sweep()  # one observation of the moved value is in the cache already
        rows = {r.premise_id: r for r in self._check(env, sw, record_id=A)}
        assert rows["p1"].confirmed == "yes"

    def test_it_writes_nothing_at_all(self, env, sw):
        """Not the ledger, and not even the cache: running it twice must not
        make a value that flaps look stable."""
        self._moved_lesson(env, sw)
        head = git(env.ledger, "rev-parse", "HEAD").stdout
        rows = self._check(env, sw)
        # control: the check really ran and saw the moved premise, so the
        # absences below are not "it saw nothing"
        assert [(r.premise_id, r.verdict) for r in rows if r.premise_id == "p1"] == [("p1", "moved")]
        self._check(env, sw)
        assert git(env.ledger, "rev-parse", "HEAD").stdout == head
        assert git(env.ledger, "status", "--porcelain").stdout == ""
        assert not (sw.cache / "premises").exists()
        assert sw.moves() == []  # and two checks never made a stable move

    def test_an_unknown_lesson_is_refused(self, env, sw):
        seed(env, A)
        with pytest.raises(LookupError):
            self._check(env, sw, record_id="lrn-0000ffff")

    def test_a_lesson_with_nothing_to_check_says_so(self, env, sw, monkeypatch):
        seed(env, A)
        monkeypatch.setattr(reachability, "reachability_rows", lambda home, claude_dir, **kw: [])
        rows = self._check(env, sw, record_id=A)
        assert [(r.kind, r.verdict) for r in rows] == [("none", "no-probe")]

    def test_a_broken_probe_is_unavailable_not_moved(self, env, sw):
        seed(env, A, [with_baseline(systemd_premise(), sw)])
        sw.runner.times_out = True
        (row,) = [r for r in self._check(env, sw, record_id=A) if r.premise_id == "p1"]
        assert row.verdict == "unavailable" and "timed out" in row.reason

    def test_the_cli_prints_baseline_current_value_and_verdict(self, env, sw, capsys, monkeypatch):
        self._moved_lesson(env, sw)
        monkeypatch.setattr(
            premise_sweep, "default_cache_dir", lambda home: sw.cache
        )
        monkeypatch.setattr(premise_sweep, "_claude_dir", lambda claude_dir: sw.claude)
        monkeypatch.setattr(
            premises, "ProbeEnv", lambda **kw: sw.probe_env(), raising=True
        )
        rc = cli.main(["premises", "check", "--id", A])
        out = capsys.readouterr().out
        assert rc == 0
        assert A in out and "p1" in out and "moved" in out
        assert "baseline: file" in out and "now:      missing" in out
        assert "(nothing to probe; written down only)" in out

    def test_the_cli_json_lists_one_row_per_premise(self, env, sw, capsys, monkeypatch):
        self._moved_lesson(env, sw)
        monkeypatch.setattr(premise_sweep, "default_cache_dir", lambda home: sw.cache)
        monkeypatch.setattr(premise_sweep, "_claude_dir", lambda claude_dir: sw.claude)
        monkeypatch.setattr(premises, "ProbeEnv", lambda **kw: sw.probe_env(), raising=True)
        rc = cli.main(["premises", "check", "--json"])
        rows = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert {"record_id", "premise_id", "verdict", "baseline_shown", "current_shown"} <= set(rows[0])
        assert {r["premise_id"] for r in rows if r["record_id"] == A} >= {"p1", "p2", "@reach"}

    def test_the_cli_refuses_a_malformed_id_and_an_unknown_lesson(self, env, capsys):
        seed(env, A)
        assert cli.main(["premises", "check", "--id", "not-an-id"]) == cli.EXIT_USAGE
        assert "not a lesson id" in capsys.readouterr().err
        assert cli.main(["premises", "check", "--id", "lrn-0000ffff"]) == cli.EXIT_USAGE
        assert "not a live routed lesson" in capsys.readouterr().err

    def test_the_cli_without_a_verb_prints_usage(self, env, capsys):
        assert cli.main(["premises"]) == cli.EXIT_USAGE
        assert "usage: self-learn premises check" in capsys.readouterr().err


# ======================================================== doctor / selftest


class TestDoctorAndSelftest:
    def test_a_failing_placement_premise_is_named_once_it_counts(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A], state="unreachable", reason="plugin-disabled")
        sw.sweep()
        one = {r.name for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + DAY)}
        assert "placement-failing" not in one  # control: one sight is not enough
        sw.sweep()
        rows = {r.name: r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + 2 * DAY)}
        assert f"{A}@reach" in rows["placement-failing"].detail
        assert rows["placement-failing"].verdict == "INFO"

    def test_placement_premises_that_could_not_be_measured_are_counted_not_failed(self, env, sw, monkeypatch):
        seed(env, A)
        fake_reach(monkeypatch, env, [A], state="unmeasurable", reason="claude-dir-absent")
        sw.sweep()
        measured_not = sum(
            1 for (_rid, pid), rows in sw.history().items() if pid.startswith("@") and rows[-1]["state"] == "unavailable"
        )
        assert measured_not >= 1  # control: the history really has such premises
        rows = {r.name: r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + DAY)}
        assert f"{measured_not} placement premise(s) could not be measured" in rows["placement-unavailable"].detail
        assert rows["placement-unavailable"].verdict == "INFO"
        assert "placement-failing" not in rows

    def test_the_row_reports_coverage_and_the_last_sweep(self, env, sw):
        seed(env, A)
        seed(env, B, [{"id": "p1", "claim": "a behaviour", "probe": None}])
        before = {r.name: r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0)}
        assert "1 of 2 placed lesson(s) record no premises yet" in before["coverage"].detail
        assert "has not run yet" in before["sweep"].detail
        sw.sweep()
        after = {r.name: r for r in premise_sweep.doctor_rows(env.ledger, sw.cache, now=T0 + 2 * DAY)}
        assert "last ran 24 hour(s) ago" in after["sweep"].detail

    def test_the_selftest_row_passes_on_a_healthy_ledger_and_is_named(self, env, capsys):
        verdict, detail = selfcheck._check_premises(env.ledger)
        assert verdict is selfcheck.Verdict.PASS
        assert "coverage" in detail
        cli.main(["--selftest"])
        assert "selftest: PASS premises" in capsys.readouterr().out

    def test_a_reader_that_cannot_read_is_a_warn_not_a_pass(self, env, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(premise_sweep, "doctor_rows", boom)
        verdict, detail = selfcheck._check_premises(env.ledger)
        assert verdict is selfcheck.Verdict.WARN and "could not be read" in detail

    def test_off_is_said_plainly(self, env, sw):
        write_config(env, "premises:\n  enabled: false\n")
        (row,) = premise_sweep.doctor_rows(env.ledger, sw.cache)
        assert row.detail.startswith("off")

    def test_doctor_premises_prints_the_rows_and_exits_zero(self, env, capsys):
        seed(env, A)
        assert cli.main(["doctor", "premises"]) == 0
        out = capsys.readouterr().out
        assert "doctor: INFO coverage" in out and "doctor: INFO sweep" in out


# ======================================================================= serve


class TestServeJob:
    def _quiet(self, monkeypatch):
        monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: False)
        monkeypatch.setattr(serve, "_overseer_is_due", lambda *a, **k: False)

    def test_the_sweep_runs_before_the_steward(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        order: list[str] = []
        self._quiet(monkeypatch)
        monkeypatch.setattr(serve, "_premises_is_due", lambda *a, **k: True)
        monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: True)
        monkeypatch.setattr(
            serve, "_run_premises_job",
            lambda home, cache, now: order.append("premises") or premise_sweep.SweepResult("ok"),
        )
        monkeypatch.setattr(
            serve, "_run_steward_job", lambda home: order.append("steward") or steward.RunResult("idle")
        )
        records = serve._run_tick(
            tmp_path / "home", cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
        )
        assert [r.name for r in records] == ["premises", "steward"]
        assert order == ["premises", "steward"]

    def test_a_stopped_refresh_is_printed_on_serves_own_output(self, tmp_path, monkeypatch, capsys):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        self._quiet(monkeypatch)
        monkeypatch.setattr(serve, "_premises_is_due", lambda *a, **k: True)
        monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: False)
        result = premise_sweep.SweepResult("ok")
        result.stopped.append("int-synthetic: a half-written ledger write")
        monkeypatch.setattr(serve, "_run_premises_job", lambda home, cache, now: result)
        serve._run_tick(tmp_path / "home", cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)
        err = capsys.readouterr().err
        assert "serve: premises job refused" in err and "int-synthetic" in err
        assert "--clear-intent int-synthetic" in err

    def test_a_held_premises_check_is_named_in_the_heartbeat_text(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        assert serve._holds_text(cache_dir, T0) == ""  # control: nothing held
        serve._write_holds(cache_dir, {"premises": {"at": T0, "cause": "wedged read", "notified_cause": "wedged read"}})
        assert "holding: premises (wedged read)" in serve._holds_text(cache_dir, T0 + 1)

    def test_a_crashed_sweep_costs_that_job_only(self, tmp_path, monkeypatch, capsys):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        self._quiet(monkeypatch)
        monkeypatch.setattr(serve, "_premises_is_due", lambda *a, **k: True)
        monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: True)

        def boom(home, cache, now):
            raise RuntimeError("synthetic crash in the sweep")

        monkeypatch.setattr(serve, "_run_premises_job", boom)
        monkeypatch.setattr(serve, "_run_steward_job", lambda home: steward.RunResult("idle"))
        records = serve._run_tick(
            tmp_path / "home", cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
        )
        assert [(r.name, r.ok) for r in records] == [("premises", False), ("steward", True)]
        assert "the premises job crashed" in capsys.readouterr().err

    def test_an_empty_ledger_runs_no_sweep_and_a_seeded_one_runs_it_once_a_day(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        self._quiet(monkeypatch)
        monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: False)
        home = make_home(tmp_path)
        assert serve._run_tick(home, cache_dir, now=T0, pid=os.getpid(), tick_secs=60.0) == []
        env = make_env(tmp_path / "second")
        seed(env, A)
        ran = serve._run_tick(env.ledger, cache_dir, now=T0, pid=os.getpid(), tick_secs=60.0)
        assert [r.name for r in ran] == ["premises"] and ran[0].ok
        assert isinstance(ran[0].result, premise_sweep.SweepResult)
        again = serve._run_tick(env.ledger, cache_dir, now=T0 + 3600, pid=os.getpid(), tick_secs=60.0)
        assert again == []  # not due again the same day
        later = serve._run_tick(env.ledger, cache_dir, now=T0 + DAY + 3600, pid=os.getpid(), tick_secs=60.0)
        assert [r.name for r in later] == ["premises"]

    def test_the_job_reads_and_writes_the_cache_the_tick_was_given(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
        cache_dir = tmp_path / "tick-cache"
        cache_dir.mkdir()
        self._quiet(monkeypatch)
        monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: False)
        env = make_env(tmp_path / "third")
        seed(env, A)
        serve._run_tick(env.ledger, cache_dir, now=T0, pid=os.getpid(), tick_secs=60.0)
        assert premise_sweep.state_path(cache_dir).is_file()
