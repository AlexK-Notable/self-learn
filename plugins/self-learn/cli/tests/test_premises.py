"""premises.py (premise-check design, unit U1; S-NEXT-u1-premises): the
``premises`` field on a record, the closed read-only probe catalog, the
probe runner and the baseline comparison.

The commands a probe may run (``systemctl``, ``pacman``, ``git``) are
FAKES on a private ``PATH`` (design §4): each prints a fixed answer,
records its argv, its environment and whether its stdin was
``/dev/null``, and writes a ``FORBIDDEN`` marker (exit 97) when called
with any verb outside the catalog -- the positive control that a refused
argv never reached a program. No real ``systemctl``/``pacman``/``git`` is
reachable from a probe in this file.

Test names avoid the words the credential-path rule refuses (a test's
``tmp_path`` directory is named after it, and a file probe under a
refused component is ``unavailable`` by design).
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from self_learn import cases, ledger_ops, premises, verbs
from self_learn.premises import (
    OBS_OK,
    OBS_UNAVAILABLE,
    PremiseError,
    ProbeEnv,
    ProbeRefused,
)
from self_learn.records import Record, ValidationError
from support import make_behavior, make_home

# ------------------------------------------------------------ fake binaries

_FAKE = '''#!{python}
import json, os, stat, sys, time
HERE = {here!r}
PROG = {prog!r}
argv = sys.argv[1:]
st0 = os.fstat(0)
dn = os.stat("/dev/null")
row = {{
    "prog": PROG,
    "argv": argv,
    "env": dict(os.environ),
    "stdin_devnull": stat.S_ISCHR(st0.st_mode) and st0.st_rdev == dn.st_rdev,
}}
with open(os.path.join(HERE, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(row) + "\\n")
FORBIDDEN_VERBS = {{
    "systemctl": {{"start", "stop", "restart", "reload", "enable", "disable", "kill",
                   "daemon-reload", "mask", "unmask", "set-property", "edit", "isolate",
                   "reset-failed", "link", "set-environment", "import-environment"}},
    "pacman": {{"-S", "-R", "-U", "-D", "-Sy", "-Syu", "--sync", "--remove", "--upgrade"}},
    "git": {{"push", "fetch", "pull", "clone", "commit", "checkout", "reset", "gc",
             "config", "remote", "show", "log", "status"}},
}}[PROG]
REQUIRED = {{"systemctl": "show", "pacman": "-Q", "git": "cat-file"}}[PROG]
if REQUIRED not in argv or any(a in FORBIDDEN_VERBS for a in argv):
    with open(os.path.join(HERE, "FORBIDDEN"), "a") as fh:
        fh.write(json.dumps(argv) + "\\n")
    sys.exit(97)
with open(os.path.join(HERE, "scenario.json")) as fh:
    scenario = json.load(fh).get(PROG, {{}})
time.sleep(scenario.get("sleep", 0))
sys.stdout.write(scenario.get("stdout", ""))
sys.stderr.write(scenario.get("stderr", ""))
sys.exit(scenario.get("rc", 0))
'''


class Fakes:
    def __init__(self, root: Path) -> None:
        self.bindir = root / "bin"
        self.bindir.mkdir(parents=True)
        self.home = root / "home"
        self.home.mkdir()
        self._scenario: dict = {}
        self._write_scenario()
        for prog in ("systemctl", "pacman", "git"):
            path = self.bindir / prog
            path.write_text(
                _FAKE.format(python=sys.executable, here=str(self.bindir), prog=prog),
                encoding="utf-8",
            )
            path.chmod(0o755)

    def _write_scenario(self) -> None:
        (self.bindir / "scenario.json").write_text(json.dumps(self._scenario), encoding="utf-8")

    def set(self, prog: str, **answer) -> None:
        self._scenario[prog] = answer
        self._write_scenario()

    def calls(self) -> list[dict]:
        log = self.bindir / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def forbidden(self) -> bool:
        return (self.bindir / "FORBIDDEN").exists()

    def env(self, **overrides) -> ProbeEnv:
        kwargs: dict[str, Any] = dict(
            home=self.home,
            path_env=str(self.bindir),
            ledger_home=None,
            runtime_dir="/nonexistent-runtime-dir",
            now=lambda: "2026-10-30T00:00:00Z",
        )
        kwargs.update(overrides)
        return ProbeEnv(**kwargs)


@pytest.fixture
def fakes(tmp_path) -> Fakes:
    # Only the shared temporary ROOT may excuse a test: a refused word in
    # a test's own directory name is a test-naming defect and must fail.
    root = os.path.realpath(tmp_path.parent)
    if premises.credential_path_problem(root, reads_content=True) is not None:
        pytest.skip(f"the temporary root {root} sits under a path premises refuse")
    return Fakes(tmp_path)


def _premise(probe, **extra) -> dict:
    out = {"id": "p1", "claim": "a fact the lesson rests on", "probe": probe}
    out.update(extra)
    return out


# ================================================================== schema


class TestSchema:
    def test_a_full_premise_list_validates(self):
        value = [
            _premise(
                {"kind": "systemd-show", "scope": "user", "unit": "x-daemon.service",
                 "property": "BindsTo"},
                holds_if="absent", match="dbus-broker.service", on_change="re-decide",
                source="case-0000000a#what_would_change[1]",
                baseline={"state": "holds", "value_sha": "0" * 32, "observed_at":
                          "2026-09-22T06:24:50Z"},
                decided_at="2026-10-30",
            ),
            {"id": "p2", "claim": "the daemon outlives a bus restart", "probe": None},
        ]
        premises.validate_premises(value)  # control: the full shape is accepted

    def test_an_empty_list_is_valid(self):
        premises.validate_premises([])

    @pytest.mark.parametrize(
        "value, words",
        [
            ({"id": "p1"}, "must be a list"),
            ([_premise(None, color="red")], "does not take"),
            ([_premise(None)] * 2, "duplicate premise id"),
            ([{"id": f"p{n}", "claim": "c", "probe": None} for n in range(1, 6)], "at most 4"),
            ([{"id": "x1", "claim": "c", "probe": None}], "p1..p4"),
            ([{"id": "p5", "claim": "c", "probe": None}], "p1..p4"),
            ([{"id": "p1", "claim": "## Decision", "probe": None}], "heading"),
            ([{"id": "p1", "claim": "two\nlines", "probe": None}], "one line"),
            ([{"id": "p1", "claim": "", "probe": None}], "non-empty"),
            ([{"id": "p1", "claim": "c" * 201, "probe": None}], "longer than"),
            ([{"id": "p1", "claim": "token = abcdefghijklmnop", "probe": None}], "secret"),
            ([{"id": "p1", "claim": "c", "probe": None, "holds_if": "absent", "match": "x"}],
             "need a probe"),
            ([_premise({"kind": "which", "name": "git"}, match="x")], "takes no match"),
            ([_premise({"kind": "which", "name": "git"}, holds_if="changed", match="x")],
             "takes no match"),
            ([_premise({"kind": "which", "name": "git"}, holds_if="not-equals", match="x")],
             "holds_if must be"),
            ([_premise({"kind": "which", "name": "git"}, holds_if="absent", match="x",
                       on_change="refresh")], "only for holds_if changed"),
            ([_premise({"kind": "which", "name": "git"}, baseline={
                "state": "holds", "value_sha": "0" * 32, "observed_at": "x", "shown": ""})],
             "non-empty"),
            ([_premise({"kind": "which", "name": "git"}, holds_if="absent")], "match"),
            ([_premise({"kind": "which", "name": "git"}, holds_if="version",
                       match=">=1.0")], "needs a package probe"),
            ([_premise({"kind": "package", "name": "git"}, holds_if="version",
                       match="about 2")], "clauses"),
            ([_premise(None, on_change="refresh")], "on_change needs a probe"),
            ([_premise({"kind": "which", "name": "git"}, on_change="later")], "on_change must"),
            ([_premise(None, baseline={"value_sha": "0" * 32, "observed_at": "x",
                                       "state": "holds"})], "no baseline"),
            ([_premise({"kind": "which", "name": "git"},
                       baseline={"value_sha": "0" * 64, "observed_at": "x", "state": "holds"})],
             "32 lowercase hex"),
            ([_premise({"kind": "which", "name": "git"},
                       baseline={"value_sha": "0" * 32, "observed_at": "x", "state": "fine"})],
             "state must be"),
            ([_premise({"kind": "which", "name": "git"},
                       baseline={"value_sha": "0" * 32, "state": "holds"})], "observed_at"),
            ([_premise({"kind": "shell", "cmd": "true"})], "probe kind must be"),
            ([_premise({"kind": "file-match", "path": "~/a.conf", "pattern": "x.*"})],
             "does not take"),
            ([_premise({"kind": "file-match", "path": "~/a.conf"})], "exactly one of"),
            ([_premise({"kind": "file-match", "path": "~/a.conf", "contains": "a", "line": "b"})],
             "exactly one of"),
            ([_premise({"kind": "file-match", "path": "~/a.conf", "lines": "9-3"})], "A-B"),
            ([_premise({"kind": "json-key", "path": "~/a.json", "key": "a..b"})], "dotted"),
            ([_premise({"kind": "systemd-show", "scope": "machine", "unit": "a.service",
                        "property": "BindsTo"})], "scope must be"),
            ([_premise({"kind": "systemd-show", "scope": "user", "unit": "-a.service",
                        "property": "BindsTo"})], "not a unit name"),
            ([_premise({"kind": "systemd-show", "scope": "user", "unit": "a.service",
                        "property": "binds to"})], "not a property name"),
            ([_premise({"kind": "package", "name": "--sync"})], "not a package name"),
            ([_premise({"kind": "which", "name": "/usr/bin/git"})], "bare command name"),
            ([_premise({"kind": "ledger", "ref": "lrn-zz"})], "ledger probe ref"),
            ([_premise({"kind": "ledger", "ref": "lrn-0000000b#body"})], "ledger probe ref"),
            ([_premise({"kind": "ledger", "ref": "stmt-0000000b#follow_up"})],
             "ledger probe ref"),
            ([_premise({"kind": "ledger", "target": "lrn-0000000b"})], "does not take"),
        ],
    )
    def test_malformed_lists_are_refused_by_name(self, value, words):
        with pytest.raises(PremiseError, match=words):
            premises.validate_premises(value)

    def test_at_most_three_premises_carry_a_probe(self):
        value = [
            {"id": f"p{n}", "claim": "c", "probe": {"kind": "which", "name": "git"}}
            for n in range(1, 4)
        ]
        premises.validate_premises(value)  # control: three probes are fine
        value.append({"id": "p4", "claim": "c", "probe": {"kind": "which", "name": "git"}})
        with pytest.raises(PremiseError, match="at most 3"):
            premises.validate_premises(value)

    @pytest.mark.parametrize("name", list(premises.PLACEMENT_PREMISE_IDS))
    def test_placement_premise_names_are_reserved(self, name):
        with pytest.raises(PremiseError, match="placement premise"):
            premises.validate_premises([{"id": name, "claim": "c", "probe": None}])
        with pytest.raises(PremiseError, match="placement premise"):
            premises.validate_premises([_premise({"kind": name})])

    def test_a_ledger_probe_may_not_name_its_own_lesson(self):
        for ref in ("lrn-0000000a", "lrn-0000000a#follow_up"):
            value = [_premise({"kind": "ledger", "ref": ref})]
            premises.validate_premises(value)  # control: fine with no record id
            with pytest.raises(PremiseError, match="its own lesson"):
                premises.validate_premises(value, record_id="lrn-0000000a")


class TestPaths:
    def test_an_ordinary_config_path_is_accepted(self):
        for kind in ("path", "file-match"):
            probe = {"kind": kind, "path": "~/.config/app/settings.conf"}
            if kind == "file-match":
                probe["contains"] = "x"
            premises.validate_probe(probe)  # control for every refusal below

    @pytest.mark.parametrize(
        "path",
        [
            "~/.ssh/config",
            "~/.ssh/id_ed25519",
            "/etc/ssh/id_rsa",
            "~/.claude/.credentials.json",
            "~/.config/bws/token.env",
            "~/repos/app/.env",
            "~/repos/app/.env.local",
            "~/.config/gh/hosts.yml",
            "~/.gnupg/pubring.kbx",
            "~/.aws/config",
            "~/.netrc",
            "~/.git-credentials",
            "/etc/shadow",
            "/etc/sudoers",
            "/proc/self/environ",
            "/sys/class/net",
            "/dev/tty",
            "/run/user/1000/bus",
            "/root/notes.txt",
            "~/.local/share/keyrings/login.keyring",
            "~/certs/server.key",
            "~/certs/server.pem",
            "~/notes/my-password-list.txt",
            "~/apps/service/secret.json",
            "~/repos/app/.git/config",
        ],
    )
    def test_credential_locations_are_refused_at_validation(self, path):
        for probe in (
            {"kind": "file-match", "path": path, "contains": "x"},
            {"kind": "json-key", "path": path, "key": "a"},
            {"kind": "path", "path": path},
        ):
            if probe["kind"] == "path" and path.endswith("/.git/config"):
                continue  # a path probe reads no content; .git is refused for reads only
            with pytest.raises(PremiseError, match="refused"):
                premises.validate_probe(probe)

    @pytest.mark.parametrize(
        "repo_path",
        [".ssh/id_rsa", "deploy/token.env", "config/.env", "certs/server.key",
         ".git/config", "ops/secrets/db.yaml", "../outside.conf", "-c"],
    )
    def test_git_file_paths_inside_a_repo_are_checked_too(self, repo_path):
        good = {"kind": "git-file", "repo": "~/repos/app", "path": "conf/app.conf",
                "contains": "x"}
        premises.validate_probe(good)  # control
        with pytest.raises(PremiseError):
            premises.validate_probe(dict(good, path=repo_path))
        with pytest.raises(PremiseError, match="refused"):
            premises.validate_probe(dict(good, repo="~/.ssh"))

    @pytest.mark.parametrize(
        "path", ["notes.txt", "./notes.txt", "~/a/../b", "~/a//b", "~other/notes", "~/"]
    )
    def test_relative_and_dotted_paths_are_refused(self, path):
        with pytest.raises(PremiseError):
            premises.validate_probe({"kind": "path", "path": path})


# ================================================================ the gate


class TestCommandGate:
    @pytest.mark.parametrize(
        "argv",
        [
            ["systemctl", "--user", "start", "x.service"],
            ["systemctl", "--user", "show", "--no-pager", "--no-ask-password", "--property",
             "BindsTo", "--value", "--", "x.service", "--now"],
            ["systemctl", "--user", "restart", "--no-pager", "--no-ask-password", "--property",
             "BindsTo", "--value", "--", "x.service"],
            ["systemctl", "--user", "show", "--no-pager", "--property", "BindsTo", "--value",
             "--", "x.service", "--no-ask-password"],
            ["sudo", "systemctl", "show", "x.service"],
            ["pkexec", "systemctl", "show", "x.service"],
            ["busctl", "call", "org.freedesktop.systemd1"],
            ["dbus-send", "--session", "/"],
            ["sh", "-c", "systemctl show x.service"],
            ["pacman", "-S", "--", "git"],
            ["pacman", "-Q", "--", "git", "extra"],
            ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C",
             "/repo", "fetch", "origin", "HEAD:x"],
            ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C",
             "/repo", "cat-file", "blob", "HEAD:../escape"],
            ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C",
             "/repo", "cat-file", "blob", "HEAD:.ssh/id_rsa"],
            [],
        ],
    )
    def test_argv_outside_the_catalog_is_refused(self, argv):
        with pytest.raises(ProbeRefused):
            premises._check_argv(argv)

    def test_the_catalog_argvs_pass_the_gate(self):
        premises._check_argv(premises._systemctl_argv("user", "x.service", "BindsTo"))
        premises._check_argv(premises._systemctl_argv("system", "x.service", "ActiveState"))
        premises._check_argv(premises._pacman_argv("git"))
        premises._check_argv(premises._git_argv("/repo", "dir/file.conf"))

    def test_a_refused_argv_never_reaches_the_runner(self, fakes):
        seen: list = []

        def runner(argv, env, timeout):
            seen.append(argv)
            return premises.CommandResult(0, b"", b"")

        env = fakes.env(runner=runner)
        premises._run_command(premises._pacman_argv("git"), env)
        assert seen  # control: a catalog argv does reach the runner
        seen.clear()
        with pytest.raises(ProbeRefused):
            premises._run_command(["systemctl", "--user", "start", "x.service"], env)
        assert seen == []

    def test_a_probe_whose_builder_goes_wrong_runs_nothing(self, fakes, monkeypatch):
        probe = {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                 "property": "BindsTo"}
        fakes.set("systemctl", stdout="y.service\n")
        first = premises.run_probe(probe, fakes.env())
        assert first.state == OBS_OK and len(fakes.calls()) == 1  # control: it runs
        monkeypatch.setattr(
            premises, "_systemctl_argv",
            lambda scope, unit, prop: ["systemctl", "--user", "start", unit],
        )
        obs = premises.run_probe(probe, fakes.env())
        assert obs.state == OBS_UNAVAILABLE
        assert obs.reason.startswith("refused")
        assert len(fakes.calls()) == 1  # the fake was not called again
        assert not fakes.forbidden()


# =============================================================== commands


class TestSystemd:
    def test_show_runs_read_only_with_stdin_from_dev_null_and_a_scrubbed_env(
        self, fakes, monkeypatch
    ):
        for name in ("DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK", "DISPLAY", "GH_TOKEN"):
            monkeypatch.setenv(name, "should-not-reach-the-probe")
        fakes.set("systemctl", stdout="dbus-broker.service\n")
        probe = {"kind": "systemd-show", "scope": "user", "unit": "x-daemon.service",
                 "property": "BindsTo"}
        obs = premises.run_probe(probe, fakes.env())
        assert obs.state == OBS_OK
        assert obs.shown == "dbus-broker.service"
        (call,) = fakes.calls()
        assert call["argv"] == [
            "--user", "show", "--no-pager", "--no-ask-password", "--property", "BindsTo",
            "--value", "--", "x-daemon.service",
        ]
        assert call["stdin_devnull"] is True
        env = call["env"]
        assert env["LC_ALL"] == "C"
        assert env["XDG_RUNTIME_DIR"] == "/nonexistent-runtime-dir"
        allowed = set(premises._child_env(fakes.env())) | {"LC_CTYPE"}
        assert set(env) - allowed == set()
        assert not fakes.forbidden()

    def test_system_scope_uses_the_system_flag(self, fakes):
        fakes.set("systemctl", stdout="active\n")
        probe = {"kind": "systemd-show", "scope": "system", "unit": "x.service",
                 "property": "ActiveState"}
        assert premises.run_probe(probe, fakes.env()).shown == "active"
        assert fakes.calls()[0]["argv"][0] == "--system"

    def test_a_failing_systemctl_is_unavailable(self, fakes):
        fakes.set("systemctl", rc=1, stderr="Failed to connect to bus\n")
        probe = {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                 "property": "BindsTo"}
        obs = premises.run_probe(probe, fakes.env())
        assert obs.state == OBS_UNAVAILABLE and obs.value_sha is None

    def test_a_probe_that_blocks_is_unavailable_within_its_bound(self, fakes):
        fakes.set("systemctl", sleep=30, stdout="never\n")
        probe = {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                 "property": "BindsTo"}
        start = time.monotonic()
        obs = premises.run_probe(probe, fakes.env(timeout=0.5))
        assert time.monotonic() - start < 5
        assert obs.state == OBS_UNAVAILABLE
        assert "timed out" in obs.reason

    def test_the_timeout_is_capped_at_five_seconds(self, fakes):
        seen: list[float] = []

        def runner(argv, env, timeout):
            seen.append(timeout)
            return premises.CommandResult(0, b"x\n", b"")

        probe = {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                 "property": "BindsTo"}
        premises.run_probe(probe, fakes.env(runner=runner, timeout=60))
        assert seen == [premises.PROBE_TIMEOUT] and premises.PROBE_TIMEOUT == 5.0

    def test_a_missing_program_is_unavailable(self, fakes, tmp_path):
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        probe = {"kind": "systemd-show", "scope": "user", "unit": "x.service",
                 "property": "BindsTo"}
        obs = premises.run_probe(probe, fakes.env(path_env=str(empty)))
        assert obs.state == OBS_UNAVAILABLE and "not installed" in obs.reason


class TestPackage:
    def test_version_and_not_installed_are_observations(self, fakes):
        probe = {"kind": "package", "name": "hyprland"}
        fakes.set("pacman", stdout="hyprland 0.56.2-1\n")
        obs = premises.run_probe(probe, fakes.env())
        assert obs.shown == "0.56.2-1"
        assert fakes.calls()[0]["argv"] == ["-Q", "--", "hyprland"]
        fakes.set("pacman", rc=1, stderr="error: package 'hyprland' was not found\n")
        gone = premises.run_probe(probe, fakes.env())
        assert gone.state == OBS_OK and gone.shown == premises.NOT_INSTALLED
        assert gone.value_sha != obs.value_sha

    @pytest.mark.parametrize(
        "answer",
        [dict(rc=2, stderr="error: could not open database\n"),
         dict(stdout="other-package 1.0-1\n"),
         dict(stdout="")],
    )
    def test_anything_else_is_unavailable(self, fakes, answer):
        fakes.set("pacman", **answer)
        obs = premises.run_probe({"kind": "package", "name": "hyprland"}, fakes.env())
        assert obs.state == OBS_UNAVAILABLE

    def test_version_range_judges_the_claim(self, fakes):
        premise = _premise({"kind": "package", "name": "hyprland"},
                           holds_if="version", match=">=0.56, <0.57")
        fakes.set("pacman", stdout="hyprland 0.56.2-1\n")
        assert premises.observe(premise, fakes.env()).claim == premises.CLAIM_HOLDS
        fakes.set("pacman", stdout="hyprland 0.57.0-1\n")
        assert premises.observe(premise, fakes.env()).claim == premises.CLAIM_CONTRADICTED
        fakes.set("pacman", rc=1, stderr="error: package 'hyprland' was not found\n")
        assert premises.observe(premise, fakes.env()).claim == premises.CLAIM_CONTRADICTED


class TestGitFile:
    def _probe(self, **matcher):
        probe = {"kind": "git-file", "repo": "~/repo", "path": "conf/app.conf"}
        probe.update(matcher or {"contains": "BindsTo=dbus-broker.service"})
        return probe

    def test_reads_head_through_cat_file_only(self, fakes):
        (fakes.home / "repo").mkdir()
        fakes.set("git", stdout="[Unit]\nBindsTo=dbus-broker.service\n")
        obs = premises.run_probe(self._probe(), fakes.env())
        assert obs.shown == premises.PRESENT
        (call,) = fakes.calls()
        assert call["argv"] == [
            "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C",
            os.path.realpath(fakes.home / "repo"), "cat-file", "blob", "HEAD:conf/app.conf",
        ]
        assert call["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert call["stdin_devnull"] is True
        assert not fakes.forbidden()

    def test_a_path_not_in_head_is_missing_and_a_broken_repo_is_unavailable(self, fakes):
        (fakes.home / "repo").mkdir()
        fakes.set("git", rc=128, stderr="fatal: path 'conf/app.conf' does not exist in 'HEAD'\n")
        assert premises.run_probe(self._probe(), fakes.env()).shown == premises.MISSING
        fakes.set("git", rc=128, stderr="fatal: not a git repository\n")
        assert premises.run_probe(self._probe(), fakes.env()).state == OBS_UNAVAILABLE

    def test_a_repo_that_does_not_exist_is_unavailable_and_runs_nothing(self, fakes):
        obs = premises.run_probe(self._probe(), fakes.env())
        assert obs.state == OBS_UNAVAILABLE
        assert fakes.calls() == []


# =================================================================== files


class TestFiles:
    def test_contains_and_line_report_markers_not_text(self, fakes):
        conf = fakes.home / "app.conf"
        conf.write_text("SENTINEL-TEXT-4711 first\nexec-once = waybar  \n", encoding="utf-8")
        present = premises.run_probe(
            {"kind": "file-match", "path": "~/app.conf", "contains": "first"}, fakes.env()
        )
        assert present.shown == premises.PRESENT
        line = premises.run_probe(
            {"kind": "file-match", "path": "~/app.conf", "line": "exec-once = waybar"},
            fakes.env(),
        )
        assert line.shown == premises.PRESENT
        absent = premises.run_probe(
            {"kind": "file-match", "path": "~/app.conf", "contains": "nowhere"}, fakes.env()
        )
        assert absent.shown == premises.ABSENT
        for obs in (present, line, absent):
            assert "SENTINEL" not in repr(obs) and "SENTINEL" not in json.dumps(obs.as_dict())

    def test_a_deleted_file_is_a_change_not_unchanged(self, fakes):
        conf = fakes.home / "app.conf"
        conf.write_text("BindsTo=dbus-broker.service\n", encoding="utf-8")
        premise = _premise(
            {"kind": "file-match", "path": "~/app.conf", "contains": "BindsTo="}
        )
        premise["baseline"] = premises.make_baseline(premises.observe(premise, fakes.env()))
        assert premises.verdict(premise, premises.observe(premise, fakes.env())) == "holds"
        conf.unlink()
        gone = premises.observe(premise, fakes.env())
        assert gone.state == OBS_OK and gone.shown == premises.MISSING
        assert premises.verdict(premise, gone) == "moved"

    def test_lines_hash_moves_only_when_those_lines_change(self, fakes):
        conf = fakes.home / "app.conf"
        conf.write_text("a\nb\nc\nd\n", encoding="utf-8")
        probe = {"kind": "file-match", "path": "~/app.conf", "lines": "2-3"}
        first = premises.run_probe(probe, fakes.env())
        assert first.shown.startswith("sha256:")
        conf.write_text("a\nb\nc\nchanged\n", encoding="utf-8")
        assert premises.run_probe(probe, fakes.env()).value_sha == first.value_sha
        conf.write_text("a\nB\nc\nd\n", encoding="utf-8")
        assert premises.run_probe(probe, fakes.env()).value_sha != first.value_sha
        conf.write_text("a\n", encoding="utf-8")
        assert premises.run_probe(probe, fakes.env()).shown == premises.OUT_OF_RANGE

    def test_a_fifo_is_unavailable_and_does_not_block(self, fakes):
        os.mkfifo(fakes.home / "pipe")
        start = time.monotonic()
        obs = premises.run_probe(
            {"kind": "file-match", "path": "~/pipe", "contains": "x"}, fakes.env()
        )
        assert time.monotonic() - start < 2
        assert obs.state == OBS_UNAVAILABLE and "regular file" in obs.reason

    def test_a_directory_and_an_oversized_file_are_unavailable(self, fakes):
        (fakes.home / "adir").mkdir()
        assert premises.run_probe(
            {"kind": "file-match", "path": "~/adir", "contains": "x"}, fakes.env()
        ).state == OBS_UNAVAILABLE
        (fakes.home / "big.conf").write_bytes(b"x" * (premises.READ_LIMIT + 1))
        big = premises.run_probe(
            {"kind": "file-match", "path": "~/big.conf", "contains": "x"}, fakes.env()
        )
        assert big.state == OBS_UNAVAILABLE and "read limit" in big.reason

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads anything")
    def test_an_unreadable_file_is_unavailable_never_missing(self, fakes):
        conf = fakes.home / "app.conf"
        conf.write_text("x\n", encoding="utf-8")
        probe = {"kind": "file-match", "path": "~/app.conf", "contains": "x"}
        assert premises.run_probe(probe, fakes.env()).shown == premises.PRESENT  # control
        conf.chmod(0)
        try:
            obs = premises.run_probe(probe, fakes.env())
        finally:
            conf.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert obs.state == OBS_UNAVAILABLE and obs.value_sha is None

    def test_a_symlink_into_a_refused_location_is_unavailable(self, fakes):
        keydir = fakes.home / ".ssh"
        keydir.mkdir()
        (keydir / "config").write_text("SENTINEL-HOSTS-4711\n", encoding="utf-8")
        (fakes.home / "plain.conf").write_text("SENTINEL-HOSTS-4711\n", encoding="utf-8")
        assert premises.run_probe(
            {"kind": "file-match", "path": "~/plain.conf", "contains": "SENTINEL"}, fakes.env()
        ).shown == premises.PRESENT  # control: the same text in a plain file is read
        (fakes.home / "link.conf").symlink_to(keydir / "config")
        obs = premises.run_probe(
            {"kind": "file-match", "path": "~/link.conf", "contains": "SENTINEL"}, fakes.env()
        )
        assert obs.state == OBS_UNAVAILABLE and "refused location" in obs.reason

    def test_path_kind_reports_type_and_link_target(self, fakes):
        (fakes.home / "f").write_text("x", encoding="utf-8")
        (fakes.home / "d").mkdir()
        (fakes.home / "l").symlink_to("f")
        shown = {
            name: premises.run_probe({"kind": "path", "path": f"~/{name}"}, fakes.env()).shown
            for name in ("f", "d", "l", "nothing-here")
        }
        assert shown == {"f": "file", "d": "dir", "l": "symlink:f", "nothing-here": "missing"}


class TestKeys:
    def test_json_key_found_missing_and_unparsable(self, fakes):
        (fakes.home / "a.json").write_text('{"hooks": {"pre": ["x", "y"]}}', encoding="utf-8")
        found = premises.run_probe(
            {"kind": "json-key", "path": "~/a.json", "key": "hooks.pre.1"}, fakes.env()
        )
        assert found.shown == '"y"'
        listed = premises.run_probe(
            {"kind": "json-key", "path": "~/a.json", "key": ["hooks", "pre", 0]}, fakes.env()
        )
        assert listed.shown == '"x"'
        missing = premises.run_probe(
            {"kind": "json-key", "path": "~/a.json", "key": "hooks.post"}, fakes.env()
        )
        assert missing.state == OBS_OK and missing.shown == premises.MISSING_KEY
        (fakes.home / "a.json").write_text("{not json", encoding="utf-8")
        broken = premises.run_probe(
            {"kind": "json-key", "path": "~/a.json", "key": "hooks"}, fakes.env()
        )
        assert broken.state == OBS_UNAVAILABLE

    def test_yaml_and_toml_keys(self, fakes):
        (fakes.home / "a.yaml").write_text("mode: plain\nlist: [1, 2]\n", encoding="utf-8")
        assert premises.run_probe(
            {"kind": "yaml-key", "path": "~/a.yaml", "key": "mode"}, fakes.env()
        ).shown == '"plain"'
        (fakes.home / "a.toml").write_text('[tool]\nname = "x"\n', encoding="utf-8")
        assert premises.run_probe(
            {"kind": "toml-key", "path": "~/a.toml", "key": "tool.name"}, fakes.env()
        ).shown == '"x"'

    def test_a_yaml_alias_bomb_is_unavailable(self, fakes):
        lines = ['a0: &a0 ["x", "x", "x", "x", "x", "x", "x", "x", "x", "x"]']
        for n in range(1, 9):
            refs = ", ".join([f"*a{n - 1}"] * 10)
            lines.append(f"a{n}: &a{n} [{refs}]")
        (fakes.home / "bomb.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        obs = premises.run_probe(
            {"kind": "yaml-key", "path": "~/bomb.yaml", "key": "a8"}, fakes.env()
        )
        assert obs.state == OBS_UNAVAILABLE and "too large" in obs.reason

    def test_long_or_risky_values_are_hashed_but_not_shown(self, fakes):
        long_value = "v" * 200
        shaped = "ghp_" + "A1b2C3d4" * 5
        (fakes.home / "a.json").write_text(
            json.dumps({"long": long_value, "shaped": shaped}), encoding="utf-8"
        )
        for key in ("long", "shaped"):
            obs = premises.run_probe(
                {"kind": "json-key", "path": "~/a.json", "key": key}, fakes.env()
            )
            assert obs.state == OBS_OK and obs.value_sha and obs.shown == ""


class TestWhichAndLedger:
    def test_which_resolves_on_the_probe_path(self, fakes):
        found = premises.run_probe({"kind": "which", "name": "git"}, fakes.env())
        assert found.shown == str(fakes.bindir / "git")
        none = premises.run_probe({"kind": "which", "name": "no-such-tool"}, fakes.env())
        assert none.state == OBS_OK and none.shown == premises.NOT_FOUND

    def test_ledger_probes_read_lessons_and_statements(self, tmp_path):
        home = make_home(tmp_path)
        ledger_ops.create_record(home, make_behavior(scope="skill:s", record_id="lrn-0000000b"))
        (home / "user-statements.jsonl").write_text(
            json.dumps({"id": "stmt-0000000b"}) + "\n"
            + json.dumps({"id": "stmt-0000000c", "amends": "stmt-0000000b"}) + "\n",
            encoding="utf-8",
        )
        env = ProbeEnv(home=tmp_path, ledger_home=home, now=lambda: "2026-10-30T00:00:00Z")
        shown = {
            target: premises.run_probe({"kind": "ledger", "ref": target}, env).shown
            for target in ("lrn-0000000b", "lrn-0000000e", "stmt-0000000b", "stmt-0000000c",
                           "stmt-0000000e")
        }
        assert shown == {
            "lrn-0000000b": "pending",
            "lrn-0000000e": premises.NOT_FOUND,
            "stmt-0000000b": "amended-by:stmt-0000000c",
            "stmt-0000000c": "current",
            "stmt-0000000e": premises.NOT_FOUND,
        }
        follow = premises.run_probe(
            {"kind": "ledger", "ref": "lrn-0000000b#follow_up"}, env
        )
        assert follow.shown == "none"
        no_ledger = premises.run_probe(
            {"kind": "ledger", "ref": "lrn-0000000b"}, ProbeEnv(home=tmp_path)
        )
        assert no_ledger.state == OBS_UNAVAILABLE


# ========================================================= judging values


class TestVerdict:
    def _obs(self, value: str, premise=None):
        return premises.observation_from_value(value, premise=premise, observed_at="t")

    def test_unavailable_is_never_holds_and_never_moved(self):
        premise = _premise({"kind": "which", "name": "git"})
        premise["baseline"] = premises.make_baseline(self._obs("/usr/bin/git"))
        assert premises.verdict(premise, self._obs("/usr/bin/git")) == "holds"  # control
        assert premises.verdict(premise, self._obs("/opt/git")) == "moved"  # control
        unavailable = premises.unavailable_observation("timed out", observed_at="t")
        assert premises.verdict(premise, unavailable) == "unavailable"

    def test_no_probe_and_no_baseline(self):
        assert premises.verdict({"id": "p1", "claim": "c", "probe": None}, None) == "no-probe"
        premise = _premise({"kind": "which", "name": "git"})
        assert premises.verdict(premise, self._obs("x")) == "no-baseline"

    def test_a_baseline_cannot_be_made_from_an_unavailable_observation(self):
        with pytest.raises(PremiseError, match="unavailable"):
            premises.make_baseline(premises.unavailable_observation("timed out"))

    def test_baseline_state_records_the_claim_judgment(self):
        premise = _premise({"kind": "which", "name": "x"}, holds_if="absent",
                           match="dbus-broker.service")
        holds = premises.make_baseline(self._obs("", premise))
        contradicted = premises.make_baseline(self._obs("dbus-broker.service", premise))
        changed = premises.make_baseline(self._obs("anything"))
        assert (holds["state"], contradicted["state"], changed["state"]) == (
            "holds", "contradicts-claim", "holds",
        )
        assert "shown" not in holds  # an empty value is not shown
        assert contradicted["shown"] == "dbus-broker.service"
        written = dict(premise, baseline=contradicted)
        premises.validate_premises([written])
        # A contradicts-claim baseline is moved from the next sweep on, even
        # though the value has not changed (02 §3a.10.4 as drafted).
        same = self._obs("dbus-broker.service", premise)
        assert premises.verdict(written, same) == "moved"
        assert premises.verdict(dict(premise, baseline=holds), self._obs("", premise)) == "holds"

    def test_a_judged_premise_moves_on_the_claim_not_on_any_change(self):
        premise = _premise({"kind": "which", "name": "x"}, holds_if="absent",
                           match="dbus-broker.service")
        premise["baseline"] = premises.make_baseline(self._obs("", premise))
        other = self._obs("other.service", premise)
        assert other.value_sha != premise["baseline"]["value_sha"]  # control: value changed
        assert premises.verdict(premise, other) == "holds"
        bound = self._obs("other.service dbus-broker.service", premise)
        assert premises.verdict(premise, bound) == "moved"

    @pytest.mark.parametrize(
        "holds_if, match, value, expected",
        [
            ("present", "BindsTo", "BindsTo=x", "holds"),
            ("present", "BindsTo", "", "contradicted"),
            ("absent", "dbus-broker.service", "", "holds"),
            ("absent", "dbus-broker.service", "dbus-broker.service", "contradicted"),
            ("equals", "active", "active", "holds"),
            ("equals", "active", "inactive", "contradicted"),
        ],
    )
    def test_holds_if(self, holds_if, match, value, expected):
        premise = _premise({"kind": "which", "name": "x"}, holds_if=holds_if, match=match)
        assert self._obs(value, premise).claim == expected

    def test_normalization_ignores_line_endings_and_trailing_space(self):
        assert premises.value_sha(premises.normalize_value("a  \r\nb\n\n")) == premises.value_sha(
            premises.normalize_value("a\nb")
        )
        assert len(premises.value_sha("x")) == 32

    def test_observe_is_total(self, fakes):
        bad = premises.observe(_premise({"kind": "shell", "cmd": "true"}), fakes.env())
        assert bad is not None and bad.state == OBS_UNAVAILABLE

        def runner(argv, env, timeout):
            raise RuntimeError("boom")

        probe = {"kind": "package", "name": "git"}
        obs = premises.observe(_premise(probe), fakes.env(runner=runner))
        assert obs is not None and obs.state == OBS_UNAVAILABLE
        assert premises.observe({"id": "p1", "claim": "c", "probe": None}, fakes.env()) is None


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("1.5.0", "1.5.0", 0),
        ("1.5.1", "1.5.0", 1),
        ("1.5.1", "1.5", 1),
        ("1.5.0-1", "1.5.0-2", -1),
        ("1.5.0-1", "1.5.1-1", -1),
        ("1.5.0-2", "1.5.1-1", -1),
        ("1.5", "1.5-1", 0),
        ("1.5b", "1.5", -1),
        ("1.5b", "1.5a", 1),
        ("1.5.1", "1.5b", 1),
        ("1.0a", "1.0alpha", -1),
        ("1.0rc", "1.0", -1),
        ("1.1", "1.1a", 1),
        ("0:1.0", "0:1.0", 0),
        ("1:1.0", "0:1.0", 1),
        ("1:1.0", "2.0", 1),
        ("1:1.0", "2:1.1", -1),
        ("0.56.2-1", "0.57", -1),
        ("10.0", "9.9", 1),
        ("1.010", "1.10", 0),
    ],
)
def test_vercmp_follows_pacman(a, b, expected):
    assert premises.vercmp(a, b) == expected
    assert premises.vercmp(b, a) == -expected


# ======================================================== record and replace


class TestRecord:
    def _value(self):
        return [
            _premise({"kind": "systemd-show", "scope": "user", "unit": "x.service",
                      "property": "BindsTo"}, holds_if="absent", match="dbus-broker.service",
                     baseline={"state": "holds", "value_sha": "a" * 32, "observed_at":
                               "2026-09-22T06:24:50Z"}),
            {"id": "p2", "claim": "the daemon outlives a bus restart", "probe": None},
        ]

    def test_premises_round_trip_through_the_record_file(self):
        record = make_behavior(record_id="lrn-0000000a")
        assert record.premises is None
        record.set_premises(self._value())
        again = Record.from_text(record.to_text())
        assert again.premises == record.premises
        assert [p["id"] for p in again.premises] == ["p1", "p2"]
        assert list(again.premises[0]) == ["id", "claim", "probe", "holds_if", "match",
                                           "baseline"]
        copy = again.premises
        copy[0]["claim"] = "poked"
        assert again.premises[0]["claim"] != "poked"

    def test_a_placed_lesson_takes_premises(self):
        record = make_behavior(record_id="lrn-0000000a")
        record.set_status("rejected")
        record.set_premises([])
        assert record.premises == []
        record.set_premises(None)
        assert record.premises is None

    def test_a_bad_list_raises_and_leaves_the_record_unchanged(self):
        record = make_behavior(record_id="lrn-0000000a")
        record.set_premises(self._value())
        with pytest.raises(ValidationError, match="premises"):
            record.set_premises([_premise({"kind": "file-match", "path": "~/.ssh/config",
                                           "contains": "x"})])
        assert record.premises[0]["id"] == "p1"

    def test_a_record_file_with_a_bad_premise_does_not_load(self):
        record = make_behavior(record_id="lrn-0000000a")
        record.set_premises([{"id": "p1", "claim": "c", "probe": None}])
        text = record.to_text()
        assert Record.from_text(text).premises  # control
        bad = text.replace("probe: null", "probe: {kind: shell, cmd: reboot}")
        assert bad != text
        with pytest.raises(ValidationError, match="premises"):
            Record.from_text(bad)

    def test_a_record_may_not_probe_its_own_status(self):
        record = make_behavior(record_id="lrn-0000000a")
        with pytest.raises(ValidationError, match="own lesson"):
            record.set_premises([_premise({"kind": "ledger", "ref": "lrn-0000000a"})])

    def test_replace_carries_premises_to_the_new_lesson(self):
        first = make_behavior(record_id="lrn-0000000a")
        first.set_premises(self._value())
        made = verbs._compose_replacement(
            first, [], scope="skill:s", new_type="behavior", kind=None,
            sections={"Trigger": "About to do X.", "Instruction": "Do Y."},
            source=None, record_id="lrn-0000000d",
        )
        assert made.supersedes == "lrn-0000000a"  # control: this is the replacement
        assert made.premises == first.premises

    def test_premises_is_a_rewrite_field(self):
        assert "premises" in cases.REWRITE_FIELDS
        block = {"ideas": [{"idea": "the binding fact", "now": "field:premises"}]}
        assert cases._rewrite_problem(block) is None
