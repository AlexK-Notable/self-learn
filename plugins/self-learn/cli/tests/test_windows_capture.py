"""The native public command boundary and its independent-shell release gate."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from self_learn import cli, miner, worker

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows capture")
linux = pytest.mark.skipif(os.name == "nt", reason="Linux capture contract")
BASIC = {"init", "list", "show", "teach", "host"}
LEDGER = set("""
bucket canary case config confirm-held confirm-recurrence defer dismiss-suspect
followup grant index link note notice proposal push reclassify reconcile reconsider rehome
reject reopen report rescope revise select sentinel statement status supersede telemetry undefer user-model
""".split())
CANON = set("batch import prune-memory recompile replace reroute retire route skill".split())
JOBS = {"mine", "overseer", "steward", "worker"}


def subcommands(parser):
    return next(a.choices for a in parser._actions if isinstance(a, argparse._SubParsersAction))


def test_capability_table_matches_parser():
    from self_learn.primitives import capabilities as cap

    choices = subcommands(cli._build_parser())
    verbs = {v for v in cap.REQUIRES if " " not in v and not v.startswith("-")}
    assert verbs == set(choices)
    expected = {
        "ledger": LEDGER | CANON | JOBS | {"doctor"},
        "canon": CANON | {"hook"},
        "hooks": {"doctor", "hook"},
        "sdk": JOBS | {"doctor", "ask", "premises", "summarise"},
        "background": JOBS | {"serve"},
        "supervisor": {"serve", "doctor"},
        "desktop": {"attention"},
    }
    assert set(cap.AVAILABLE) == set(expected)
    for capability, needs_it in expected.items():
        assert {v for v in verbs if capability in cap.REQUIRES[v]} == needs_it
    assert {v for v in verbs if not cap.REQUIRES[v]} == BASIC
    assert set(subcommands(choices["host"])) == {"add", "list", "rebind", "commit-drift", "remove", "set-mode"}


def minimum_arguments(parser):
    """Build syntactically valid inputs for each real parser, including required groups."""
    args = []
    grouped = {g._group_actions[0] for g in parser._mutually_exclusive_groups if g.required}
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            name, child = next(iter(a.choices.items()))
            args.extend([name, *minimum_arguments(child)])
        elif a.required or a in grouped:
            if a.option_strings:
                args.append(a.option_strings[0])
            if a.nargs != 0:
                args.append(str(next(iter(a.choices))) if a.choices else "1")
    return args


@windows
def test_refusal_profile_precedes_dispatch(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("refusal reached watchdog, provider, child process or selfcheck")

    for module, attr in [(miner, "maybe_kick"), (worker, "kick"), (cli.selfcheck, "run_selftest"),
                         (cli.gitops.procs, "run_command"), (cli.gitops.procs, "run_bounded")]:
        monkeypatch.setattr(module, attr, forbidden)
    parser = cli._build_parser()
    choices = subcommands(parser)
    forms = [([v, *minimum_arguments(choices[v])], v) for v in sorted(choices.keys() - BASIC)]
    for v, child in subcommands(choices["host"]).items():
        if v not in ("add", "list"):
            forms.append((["host", v, *minimum_arguments(child)], "host"))
    for opt in ["--route", "--allow-empty-glob", "--allow-unpathed"]:
        forms.append((["teach", opt], "teach"))
    for opt in ["--dest", "--note", "--hook-input", "--rules-path", "--follow-up", "--unblocks-on", "--follow-up-note"]:
        forms.append((["teach", opt + "="], "teach"))
    forms.append((["--selftest"], "--selftest"))
    sentinel = tmp_path / "visible"
    sentinel.write_bytes(b"baseline")
    baseline = set(tmp_path.rglob("*"))
    for argv, verb in forms:
        assert cli.main(argv) == 1, argv
        captured = capsys.readouterr()
        assert (captured.out, captured.err) == ("", f"self-learn {verb}: unavailable in Windows capture mode\n"), argv
    assert cli.main(["mine", "--unknown-option"]) == 2
    assert "unrecognized" in capsys.readouterr().err
    assert cli.main(["mine", "--help"]) == 0
    assert "usage:" in capsys.readouterr().out
    assert set(tmp_path.rglob("*")) == baseline and sentinel.read_bytes() == b"baseline"


@windows
def test_background_kicks_refuse_before_settings(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("kick reached settings or cache")
    monkeypatch.setattr(worker, "_autokick_disabled", forbidden)
    monkeypatch.setattr(miner.settings, "resolve_setting", forbidden)
    assert worker.kick(tmp_path) == miner.maybe_kick(tmp_path) == "disabled"


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                          stdout=subprocess.PIPE, timeout=30).stdout


def scratch_env(root):
    profile = root / "profile"
    env = os.environ.copy()
    paths = {
        "HOME": profile, "USERPROFILE": profile, "XDG_CACHE_HOME": root / "cache",
        "SELF_LEARN_HOME": root / "ledger", "CODEX_HOME": profile / ".codex",
        "SELF_LEARN_CLAUDE_DIR": profile / ".claude", "SELF_LEARN_AGENTS_DIR": profile / ".agents",
        "APPDATA": profile / "roaming", "LOCALAPPDATA": profile / "local",
        "WIN_PD_OVERRIDE_APPDATA": profile / "roaming", "WIN_PD_OVERRIDE_LOCAL_APPDATA": profile / "local",
        "GIT_CONFIG_GLOBAL": profile / "gitconfig",
    }
    env.update({k: str(v) for k, v in paths.items()})
    for key in ("HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA", "SELF_LEARN_CLAUDE_DIR",
                "CODEX_HOME", "SELF_LEARN_AGENTS_DIR"):
        paths[key].mkdir(exist_ok=True, parents=True)
    env.update(GIT_AUTHOR_NAME="Capture Test", GIT_COMMITTER_NAME="Capture Test",
               GIT_AUTHOR_EMAIL="capture@example.invalid", GIT_COMMITTER_EMAIL="capture@example.invalid",
               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", SELF_LEARN_ACTOR="capture-test")
    if os.name == "nt":
        env["HOMEDRIVE"], env["HOMEPATH"] = os.path.splitdrive(str(profile))
    return env


@linux
def test_linux_teach_never_imports_capabilities(tmp_path):
    env = scratch_env(tmp_path)
    code = """
import sys
from self_learn.cli import main
from self_learn import gitops, ledger
from unittest.mock import patch
with patch.object(gitops, '_git', wraps=gitops._git) as commands:
    assert main(['init']) == 0
    assert main(['init']) == 0
    assert all('config' not in call.args[1:] for call in commands.call_args_list)
assert ledger.resolve_home() == __import__('pathlib').Path(__import__('os').environ['SELF_LEARN_HOME'])
assert main(['teach','--user','--no-push','--fact','synthetic capture']) == 0
assert 'self_learn.primitives.capabilities' not in sys.modules
assert 'self_learn.primitives._capture_windows' not in sys.modules
from self_learn import cli
with patch.object(cli.miner, 'maybe_kick', return_value='disabled') as watchdog:
    assert main(['status', '--unexpected']) == cli.EXIT_USAGE
    watchdog.assert_called_once_with(ledger.resolve_home(), no_push=False)
"""
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True, timeout=60)


# Loaded by the *actual CLI interpreter* in both shells. Observe the selected
# image before native creation, and also catch subprocess.Popen (SDK/workers).
OBSERVER = """
import os, sys, win32process
from pathlib import Path
def observe(program):
    name = Path(program).name.lower()
    with open(os.environ['CAPTURE_OBSERVED'], 'a', encoding='utf-8') as stream:
        print(name, file=stream)
    if name not in ('git.exe', 'git'):
        raise RuntimeError('unexpected child ' + name)
original = win32process.CreateProcess
def create(program, *args):
    observe(program)
    return original(program, *args)
def audit(event, args):
    if event == 'subprocess.Popen':
        # Windows supplies a command line when lpApplicationName is NULL.
        import win32api
        observe(args[0] or win32api.CommandLineToArgv(args[1])[0])
win32process.CreateProcess = create
sys.addaudithook(audit)
"""


@windows
@pytest.mark.parametrize("utf8", [False, True], ids=["default", "utf8"])
def test_two_powershell_processes_share_committed_capture(tmp_path, utf8):
    env = scratch_env(tmp_path)
    if utf8:
        env["PYTHONUTF8"] = "1"
    else:
        env.pop("PYTHONUTF8", None)
        env.pop("PYTHONIOENCODING", None)
    host = tmp_path / "projet été [1]"
    host.mkdir()
    ledger = Path(env["SELF_LEARN_HOME"])
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote), env=env)
    git(tmp_path, "config", "--global", "core.autocrlf", "true", env=env)
    git(host, "init", env=env)
    git(host, "config", "core.longpaths", "false", env=env)
    dirty = host / "unrelated"
    dirty.write_bytes(b"original\n")
    git(host, "add", "unrelated", env=env)
    git(host, "commit", "-m", "seed", env=env)
    dirty.write_bytes(b"dirty host\n")
    host_status = git(host, "status", "--porcelain", "-z", env=env)
    assert host_status == b" M unrelated\0"
    host_entries = set(host.iterdir())
    guard = Path(env["XDG_CACHE_HOME"]) / "guard"
    guard.write_bytes(b"cache guard")
    observer = tmp_path / "observer"
    observer.mkdir()
    (observer / "sitecustomize.py").write_text(OBSERVER, encoding="utf-8")
    log = tmp_path / "observed"
    env.update(PYTHONPATH=str(observer), CAPTURE_OBSERVED=str(log),
               CAPTURE_CLI=str(Path(sys.executable).with_name("self-learn.exe")),
               CAPTURE_ROOT=str(tmp_path), CAPTURE_REMOTE=str(remote),
               SELF_LEARN_WORKER_AUTOKICK="1", SELF_LEARN_MINER_AUTOKICK="1")
    probe = subprocess.run([sys.executable, "-c", "import subprocess; subprocess.run(['synthetic-worker-sdk.exe'])"],
                           env=env, capture_output=True, timeout=20)
    assert probe.returncode and b"unexpected child synthetic-worker-sdk.exe" in probe.stderr
    assert log.read_text().splitlines() == ["synthetic-worker-sdk.exe"]

    def shell(body):
        # Throw immediately at the native command that failed.
        prelude = "$ErrorActionPreference='Stop'\n$PSNativeCommandUseErrorActionPreference=$true\n"
        result = subprocess.run(["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", prelude + body],
                                cwd=host, env=env, capture_output=True, timeout=120)
        assert result.returncode == 0, (result.stdout, result.stderr)
        return json.loads(result.stdout.decode("utf-8-sig"))

    a = shell("""
& $env:CAPTURE_CLI init | Out-Null
& $env:CAPTURE_CLI host add (Get-Location).Path | Out-Null
$h = $env:SELF_LEARN_HOME
git -C $h remote add origin $env:CAPTURE_REMOTE
git -C $h push --quiet origin HEAD:refs/heads/seed
$before = git -C $h rev-parse HEAD
[IO.File]::WriteAllText((Join-Path $h sentinel), 'index sentinel')
git -C $h add -- sentinel
$receipt = & $env:CAPTURE_CLI teach --project --no-push --json --fact 'Synthetic café evidence' | ConvertFrom-Json
@{pid=$PID; receipt=$receipt; rel=[IO.Path]::GetRelativePath($h,$receipt.path); before=$before} | ConvertTo-Json -Compress
""")
    record_id = a["receipt"]["id"]
    env.update(CAPTURE_ID=record_id, CAPTURE_REL=a["rel"].replace("\\", "/"))
    b = shell("""
$h = $env:SELF_LEARN_HOME
$show = & $env:CAPTURE_CLI show $env:CAPTURE_ID --json | ConvertFrom-Json
$list = & $env:CAPTURE_CLI list --json | ConvertFrom-Json
$hostsText = & $env:CAPTURE_CLI host list
$blob = git -C $h show "HEAD:$env:CAPTURE_REL"
@{pid=$PID; shown=$show.id; ids=@($list | ForEach-Object {$_.id}); hosts=($hostsText -join ' '); blob=($blob -join [char]10)} | ConvertTo-Json -Compress
""")
    assert a["pid"] != b["pid"] and b["shown"] == record_id and b["ids"] == [record_id]
    assert str(host) in b["hosts"] and "Synthetic café evidence" in b["blob"]
    record = ledger / a["rel"]
    stored = git(ledger, "show", "HEAD:" + env["CAPTURE_REL"], env=env)
    assert stored == record.read_bytes() and b"Synthetic caf\xc3\xa9 evidence" in stored
    from ruamel.yaml import YAML
    assert Path(YAML(typ="safe").load((record.parents[1] / "meta.yaml").read_bytes())["path"]) == host
    assert git(remote, "rev-parse", "refs/heads/seed", env=env).decode().strip() == a["before"]
    assert git(ledger, "rev-parse", "HEAD", env=env).decode().strip() != a["before"]
    assert git(ledger, "diff", "--cached", "--name-only", "-z", env=env) == b"sentinel\0"
    assert git(ledger, "show", ":sentinel", env=env) == (ledger / "sentinel").read_bytes() == b"index sentinel"
    assert set(host.iterdir()) == host_entries and dirty.read_bytes() == b"dirty host\n"
    assert git(host, "status", "--porcelain", "-z", env=env) == host_status
    observed = log.read_text().splitlines()
    assert "git.exe" in observed and set(observed[1:]) <= {"git", "git.exe"}
    assert guard.read_bytes() == b"cache guard"
    assert not list(guard.parent.rglob("worker.dirty")) and not list(guard.parent.rglob("miner.spawn.lock"))
    assert git(host, "config", "--local", "core.longpaths", env=env).strip() == b"false"
    assert git(host, "config", "--global", "core.autocrlf", env=env).strip() == b"true"
