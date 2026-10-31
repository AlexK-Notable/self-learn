"""A path on a filesystem that is not mounted is `unavailable`, not `missing`
(premises design lane P3; S-NEXT-probes-chain; 02 §3a.10.2 rule 4,
§3a.10.5 (3), §3a.10.6).

Every mount table here is a fake (:class:`premises.MountTable` injected
through ``ProbeEnv.mounts``); no real mount is read or made. The "mount
points" are directories under ``tmp_path`` (or a removable-media path that
does not exist on any host), so a path under one that is "not mounted" is
simply absent on disk, exactly what ``lstat`` sees for a real unmounted
disk. No model is called; the sweep's days are simulated by ``now=``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from self_learn import premise_sweep, premises, steward_inputs
from self_learn.overseer import health
from self_learn.premises import CommandResult, MountTable, ProbeEnv
from support import commit_all, make_behavior, make_env

DAY = 24 * 3600
T0 = datetime(2026, 10, 31, 3, 30, tzinfo=timezone.utc).timestamp()
A = "lrn-0000b001"


def table(*, current=None, declared=(), readable=True) -> MountTable:
    return MountTable(current=dict(current or {}), declared=frozenset(declared), readable=readable)


def penv(tmp_path: Path, mounts: MountTable, **kw) -> ProbeEnv:
    def runner(argv, env, timeout):
        raise AssertionError(f"no command may run here: {argv}")

    return ProbeEnv(
        home=tmp_path, path_env=kw.pop("path_env", "/nonexistent-bin"), runner=runner,
        runtime_dir="/nonexistent-runtime-dir", mounts=lambda: mounts, **kw,
    )


def path_obs(target: Path | str, env: ProbeEnv) -> premises.Observation:
    return premises.run_probe({"kind": "path", "path": str(target)}, env)


@pytest.fixture
def disk(tmp_path):
    """A "mount point" directory path (not created) and a file below it."""
    point = tmp_path / "mnt-x"
    return point, point / "data" / "notes.txt"


# ============================================================ the probe


class TestPathProbe:
    def test_a_declared_mount_that_is_not_mounted_is_unavailable(self, tmp_path, disk):
        point, target = disk
        obs = path_obs(target, penv(tmp_path, table(declared={str(point)})))
        assert obs.state == premises.OBS_UNAVAILABLE, obs
        assert obs.cause == premises.CAUSE_MOUNT_ABSENT
        assert obs.mount == str(point)
        assert f"the filesystem mounted at {point} is not mounted" in obs.reason

    def test_a_deletion_on_a_mounted_filesystem_is_still_missing(self, tmp_path, disk):
        point, target = disk
        target.parent.mkdir(parents=True)
        target.write_text("x")
        mounted = table(current={str(point): "ext4"}, declared={str(point)})
        assert path_obs(target, penv(tmp_path, mounted)).shown == "file"  # control
        target.unlink()
        obs = path_obs(target, penv(tmp_path, mounted))
        assert obs.state == premises.OBS_OK and obs.shown == premises.MISSING, obs
        assert obs.cause == ""

    def test_a_path_under_no_declared_mount_is_missing(self, tmp_path, disk):
        _point, target = disk
        obs = path_obs(target, penv(tmp_path, table(declared={"/elsewhere"})))
        assert obs.state == premises.OBS_OK and obs.shown == premises.MISSING, obs

    def test_an_unreadable_table_with_a_covering_declared_mount_is_unavailable(self, tmp_path, disk):
        point, target = disk
        obs = path_obs(target, penv(tmp_path, table(declared={str(point)}, readable=False)))
        assert obs.state == premises.OBS_UNAVAILABLE, obs
        assert obs.cause == premises.CAUSE_MOUNT_UNKNOWN
        assert "cannot tell whether the filesystem" in obs.reason

    def test_an_unreadable_table_with_no_covering_mount_keeps_missing(self, tmp_path, disk):
        _point, target = disk
        obs = path_obs(target, penv(tmp_path, table(declared={"/elsewhere"}, readable=False)))
        assert obs.shown == premises.MISSING, obs

    def test_a_reader_that_raises_reads_as_an_unreadable_table(self, tmp_path, disk):
        point, target = disk
        declared_only = table(declared={str(point)})

        def boom():
            raise OSError("synthetic")

        env = ProbeEnv(home=tmp_path, path_env="/nonexistent-bin", mounts=boom)
        # nothing is declared once the reader fails, so this is plain `missing`
        assert path_obs(target, env).shown == premises.MISSING
        assert path_obs(target, penv(tmp_path, declared_only)).cause == premises.CAUSE_MOUNT_ABSENT

    def test_a_removable_media_root_that_is_absent_is_unavailable(self, tmp_path):
        # `/media/<label>` through a path probe; `/run/media/<user>/<label>`
        # (never probed directly: /run is a denied root) through `which`'s PATH.
        target = "/media/nobody-self-learn-test-label/photos/a.jpg"
        assert not os.path.lexists(target)  # control: nothing there on this host
        obs = path_obs(target, penv(tmp_path, table()))
        assert obs.state == premises.OBS_UNAVAILABLE, obs
        assert obs.mount == "/media/nobody-self-learn-test-label"
        assert obs.cause == premises.CAUSE_MOUNT_ABSENT
        run_media = "/run/media/nobody-self-learn-test/LABEL"
        which = premises.run_probe(
            {"kind": "which", "name": "self-learn-no-such-tool"},
            penv(tmp_path, table(), path_env=f"{run_media}/bin"),
        )
        assert which.state == premises.OBS_UNAVAILABLE and which.mount == run_media, which
        mounted = premises.run_probe(
            {"kind": "which", "name": "self-learn-no-such-tool"},
            penv(tmp_path, table(current={run_media: "vfat"}), path_env=f"{run_media}/bin"),
        )
        assert mounted.shown == premises.NOT_FOUND, mounted  # control

    def test_an_automount_that_did_not_mount_is_unavailable(self, tmp_path, disk):
        point, target = disk
        obs = path_obs(target, penv(tmp_path, table(current={str(point): "autofs"}, declared={str(point)})))
        assert obs.state == premises.OBS_UNAVAILABLE and obs.cause == premises.CAUSE_MOUNT_ABSENT, obs
        assert "automount" in obs.reason

    def test_the_longest_covering_mount_decides(self, tmp_path, disk):
        point, target = disk
        outer = tmp_path
        obs = path_obs(
            target,
            penv(tmp_path, table(current={str(outer): "ext4"}, declared={str(outer), str(point)})),
        )
        assert obs.cause == premises.CAUSE_MOUNT_ABSENT and obs.mount == str(point), obs

    def test_a_prefix_that_is_not_a_whole_component_does_not_cover(self, tmp_path):
        target = tmp_path / "mnt-xy" / "f"
        obs = path_obs(target, penv(tmp_path, table(declared={str(tmp_path / "mnt-x")})))
        assert obs.shown == premises.MISSING, obs

    def test_the_mount_table_is_read_once_per_env(self, tmp_path, disk):
        point, target = disk
        reads = []

        def reader():
            reads.append(1)
            return table(declared={str(point)})

        env = ProbeEnv(home=tmp_path, path_env="/nonexistent-bin", mounts=reader)
        path_obs(target, env)
        path_obs(target, env)
        assert reads == [1]


class TestTheOtherKinds:
    def test_a_file_match_says_why_with_the_cause(self, tmp_path, disk):
        point, target = disk
        probe = {"kind": "file-match", "path": str(target), "lines": "1-2"}
        absent = premises.run_probe(probe, penv(tmp_path, table(declared={str(point)})))
        assert absent.state == premises.OBS_UNAVAILABLE and absent.cause == premises.CAUSE_MOUNT_ABSENT
        assert "is not mounted" in absent.reason
        mounted = premises.run_probe(
            probe, penv(tmp_path, table(current={str(point): "ext4"}, declared={str(point)}))
        )
        assert mounted.reason == "the file does not exist" and mounted.cause == ""

    def test_which_with_a_path_dir_under_an_absent_mount_is_unavailable(self, tmp_path, disk):
        point, _target = disk
        probe = {"kind": "which", "name": "self-learn-no-such-tool"}
        path_env = f"/nonexistent-bin{os.pathsep}{point}/bin"
        obs = premises.run_probe(probe, penv(tmp_path, table(declared={str(point)}), path_env=path_env))
        assert obs.state == premises.OBS_UNAVAILABLE and obs.cause == premises.CAUSE_MOUNT_ABSENT, obs
        mounted = premises.run_probe(
            probe,
            penv(tmp_path, table(current={str(point): "ext4"}, declared={str(point)}), path_env=path_env),
        )
        assert mounted.shown == premises.NOT_FOUND, mounted  # control: a real not-found stays a value

    def test_a_git_file_repo_under_an_absent_mount_is_waiting(self, tmp_path, disk):
        point, _target = disk
        probe = {"kind": "git-file", "repo": str(point / "repo"), "path": "a.txt", "lines": "1-1"}
        obs = premises.run_probe(probe, penv(tmp_path, table(declared={str(point)})))
        assert obs.state == premises.OBS_UNAVAILABLE and obs.cause == premises.CAUSE_MOUNT_ABSENT, obs


class TestReadMountTable:
    def test_it_parses_mountinfo_fstab_and_units(self, tmp_path):
        mountinfo = tmp_path / "mountinfo"
        mountinfo.write_text(
            "22 1 259:2 / / rw,relatime shared:1 - ext4 /dev/root rw\n"
            "40 22 0:40 / /mnt/with\\040space rw shared:9 - xfs /dev/sdb1 rw\n"
            "41 22 0:41 / /mnt/auto rw shared:10 - autofs systemd-1 rw\n"
            "42 41 0:42 / /mnt/auto rw shared:11 - ext4 /dev/sdc1 rw\n"
            "garbage line\n"
        )
        fstab = tmp_path / "fstab"
        fstab.write_text(
            "# comment\n"
            "UUID=a / ext4 defaults 0 1\n"
            "UUID=b /mnt/nvme-1tb ext4 nofail,x-systemd.device-timeout=10s 0 2\n"
            "UUID=c none swap sw 0 0\n"
            "/swapfile swap swap defaults 0 0\n"
        )
        units = tmp_path / "units"
        units.mkdir()
        (units / "srv-data.mount").write_text("[Mount]\nWhere=/srv/data\nWhat=/dev/sdd1\n")
        (units / "srv-auto.automount").write_text("[Automount]\nWhere = /srv/auto\n")
        (units / "x.service").write_text("[Service]\nWhere=/not/a/mount\n")
        got = premises.read_mount_table(str(mountinfo), str(fstab), str(units))
        assert got.readable
        assert got.current["/mnt/with space"] == "xfs"
        assert got.current["/mnt/auto"] == "ext4"  # the mount on top of the trap
        assert got.declared == frozenset({"/", "/mnt/nvme-1tb", "/srv/data", "/srv/auto"})

    def test_a_missing_mountinfo_is_unreadable(self, tmp_path):
        got = premises.read_mount_table(str(tmp_path / "no"), str(tmp_path / "no"), str(tmp_path / "no"))
        assert not got.readable and got.declared == frozenset() and dict(got.current) == {}


# ============================================== the sweep and the readers


class Sweeper:
    def __init__(self, env, tmp_path, point: Path, target: Path):
        self.env = env
        self.cache = tmp_path / "cache"
        self.claude = tmp_path / "no-claude-dir"
        self.point = point
        self.target = target
        self.mounted = False
        self.day = 0

    def probe_env(self) -> ProbeEnv:
        current = {str(self.point): "ext4"} if self.mounted else {}
        return ProbeEnv(
            home=self.point.parent, path_env="/nonexistent-bin",
            runner=lambda *a: CommandResult(1, b"", b""), runtime_dir="/nonexistent-runtime-dir",
            mounts=lambda: table(current=current, declared={str(self.point)}),
        )

    def sweep(self, day: int | None = None):
        self.day = self.day + 1 if day is None else day
        return premise_sweep.run(
            self.env.ledger, self.cache, now=T0 + self.day * DAY, env=self.probe_env(),
            claude_dir=self.claude,
        )

    def rows(self):
        return premise_sweep.read_history(self.cache)[(A, "p1")]

    def doctor(self):
        return premise_sweep.doctor_rows(self.env.ledger, self.cache, now=T0 + self.day * DAY)


@pytest.fixture
def sandbox(tmp_path, monkeypatch, disk):
    root = os.path.realpath(tmp_path.parent)
    if premises.credential_path_problem(root, reads_content=True) is not None:
        pytest.skip(f"the temporary root {root} sits under a path premises refuse")
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    point, target = disk
    sw = Sweeper(e, tmp_path, point, target)
    monkeypatch.setattr(premise_sweep, "default_cache_dir", lambda home: sw.cache)
    premise = {
        "id": "p1", "claim": "the notes file is there",
        "probe": {"kind": "path", "path": str(target)},
        "baseline": {
            **premises.make_baseline(premises.observation_from_value("file")),
            "observed_at": "2026-09-22T06:24:50Z",
        },
    }
    resolved = e.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record = make_behavior(scope="skill:s", record_id=A)
    record.set_routing({"routed_at": "2026-09-22T06:24:50Z", "destination": "skill-md", "by": "human"})
    record.set_status("routed")
    record.set_premises([premise])
    record.write(resolved / f"{A}.md")
    commit_all(e.ledger, f"seed {A}")
    return sw


def broken_everywhere(sw: Sweeper) -> tuple[bool, bool, bool]:
    doctor = any(r.name == "broken-probes" and f"{A}/p1" in r.detail for r in sw.doctor())
    briefs = A in steward_inputs.broken_probes(sw.env.ledger)
    facts = health.premise_facts(sw.env.ledger, cache_dir=sw.cache)
    overseer = any(b.get("lesson") == A for b in facts.get("broken_probes", []))
    return doctor, briefs, overseer


class TestWaitingIsNotBroken:
    def test_three_mount_absent_sweeps_are_waiting_in_every_reader(self, sandbox):
        sw = sandbox
        for _ in range(3):
            sw.sweep()
        rows = sw.rows()
        assert [r["cause"] for r in rows] == [premises.CAUSE_MOUNT_ABSENT] * 3  # control
        assert broken_everywhere(sw) == (False, False, False)
        (waiting,) = [r for r in sw.doctor() if r.name == "waiting-for-filesystem"]
        assert waiting.verdict == "INFO"
        assert f"{sw.point} not mounted (1 probe(s), since {rows[0]['observed_at']})" in waiting.detail

    def test_control_three_other_unavailable_sweeps_are_broken_in_every_reader(self, sandbox, monkeypatch):
        sw = sandbox
        monkeypatch.setattr(
            premises, "_absent_mount",
            lambda target, env: premises._Unavailable("synthetic: could not look"),
        )
        for _ in range(3):
            sw.sweep()
        assert broken_everywhere(sw) == (True, True, True)

    def test_thirty_one_days_absent_counts_as_broken(self, sandbox):
        sw = sandbox
        sw.sweep(day=1)
        first = sw.rows()[-1]["observed_at"]
        for day in (2, 3):
            sw.sweep(day=day)
        assert broken_everywhere(sw) == (False, False, False)  # control: still waiting
        for day in (30, 31, 32):
            sw.sweep(day=day)
        rows = sw.rows()
        assert [r["absent_since"] for r in rows] == [first] * 3  # carried across sweeps
        assert broken_everywhere(sw) == (True, True, True)
        assert not [r for r in sw.doctor() if r.name == "waiting-for-filesystem"]

    def test_absent_since_restarts_after_the_mount_comes_back(self, sandbox):
        sw = sandbox
        sw.sweep(day=1)
        sw.mounted = True
        sw.target.parent.mkdir(parents=True)
        sw.sweep(day=2)
        assert sw.rows()[-1]["shown"] == premises.MISSING  # mounted: a real absence
        sw.target.parent.rmdir()
        sw.mounted = False
        sw.sweep(day=3)
        assert sw.rows()[-1]["absent_since"] == sw.rows()[-1]["observed_at"]

    def test_the_cause_round_trips_through_the_cache_row(self, sandbox):
        sw = sandbox
        sw.sweep()
        (row,) = sw.rows()
        assert row["cause"] == premises.CAUSE_MOUNT_ABSENT and row["mount"] == str(sw.point)
        obs = premise_sweep._obs(row)
        assert obs.cause == premises.CAUSE_MOUNT_ABSENT and obs.mount == str(sw.point)


class TestAbsentSince:
    PREV = {"cause": premises.CAUSE_MOUNT_ABSENT, "mount": "/mnt/x", "psha": "q",
            "observed_at": "2026-10-02T00:00:00Z", "absent_since": "2026-10-01T00:00:00Z"}

    def test_it_is_carried_from_the_same_absent_mount(self):
        row = {**self.PREV, "observed_at": "2026-10-03T00:00:00Z", "absent_since": None}
        assert premise_sweep._absent_since(self.PREV, row) == "2026-10-01T00:00:00Z"

    def test_another_mount_point_starts_afresh(self):
        row = {**self.PREV, "mount": "/mnt/y", "observed_at": "2026-10-03T00:00:00Z"}
        assert premise_sweep._absent_since(self.PREV, row) == "2026-10-03T00:00:00Z"

    def test_another_question_starts_afresh(self):
        row = {**self.PREV, "psha": "other", "observed_at": "2026-10-03T00:00:00Z"}
        assert premise_sweep._absent_since(self.PREV, row) == "2026-10-03T00:00:00Z"


class TestBrokenTail:
    PREMISE = {"id": "p1", "claim": "c", "probe": {"kind": "path", "path": "/mnt/x/f"}}

    def rows(self, days, *, since_day, cause=premises.CAUSE_MOUNT_ABSENT):
        sig = premise_sweep._premise_sig(self.PREMISE)

        def at(d):
            return datetime.fromtimestamp(T0 + d * DAY, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return [
            {"psha": sig, "state": premises.OBS_UNAVAILABLE, "cause": cause, "mount": "/mnt/x",
             "observed_at": at(d), "sweep": at(d), "absent_since": at(since_day), "reason": "r"}
            for d in days
        ]

    def test_waiting_inside_thirty_days(self):
        assert premise_sweep.broken_tail(self.PREMISE, self.rows([27, 28, 29], since_day=0)) is None
        assert premise_sweep.waiting_for_mount(self.PREMISE, self.rows([27, 28, 29], since_day=0))

    def test_broken_at_thirty_one_days(self):
        tail = premise_sweep.broken_tail(self.PREMISE, self.rows([29, 30, 31], since_day=0))
        assert tail is not None and len(tail) == premise_sweep.BROKEN_PROBE_SWEEPS
        assert premise_sweep.waiting_for_mount(self.PREMISE, self.rows([29, 30, 31], since_day=0)) is None

    def test_other_causes_are_broken_at_once(self):
        assert premise_sweep.broken_tail(self.PREMISE, self.rows([1, 2, 3], since_day=1, cause="")) is not None

    def test_a_row_of_another_question_does_not_count(self):
        rows = self.rows([1, 2, 3], since_day=1, cause="")
        rows[0]["psha"] = "other"
        assert premise_sweep.broken_tail(self.PREMISE, rows) is None
