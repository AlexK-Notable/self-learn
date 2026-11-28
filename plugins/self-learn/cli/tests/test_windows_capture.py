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


L, C, H, S, B, V, D = "ledger", "canon", "hooks", "sdk", "background", "supervisor", "desktop"
# Every subcommand path and what it needs, spelled out independently of the table.
SUBFORMS = {
    **dict.fromkeys(("host add", "host list"), set()),
    **dict.fromkeys(("host rebind", "host remove", "host set-mode"), {L}),
    "host commit-drift": {L, C},
    "link contradicts": {L},
    **dict.fromkeys(("hook activate", "hook deactivate"), {C, H}),
    **dict.fromkeys(("followup done", "followup add"), {L}),
    "premises check": {S},
    **dict.fromkeys(("notice list", "notice done"), {L}),
    **dict.fromkeys(("telemetry note", "telemetry flush", "telemetry read-observed"), {L}),
    "worker kick": {L, B}, "worker run": {L, S}, "overseer run": {L, S},
    **dict.fromkeys(("overseer status", "overseer report", "overseer open", "overseer respond"), {L}),
    **dict.fromkeys(("index status", "index build", "index related", "index groups"), {L}),
    **dict.fromkeys(("skill write", "skill retire", "skill rename", "skill veto", "skill register",
                     "skill unregister"), {L, C}),
    "skill list": {L},
    **dict.fromkeys(("skill request build", "skill request change", "skill request withdraw"), {L}),
    **dict.fromkeys(("skill reference show", "skill reference check", "skill reference status"), {L}),
    **dict.fromkeys(("skill script list", "skill script show"), {L}),
    **dict.fromkeys(("skill script draft", "skill script activate", "skill script deactivate"), {L, H}),
    "skill script review": {L, S, H},
    **dict.fromkeys(("attention seen", "attention packet", "attention feedback", "attention answer",
                     "attention undo"), {D}),
    **dict.fromkeys(("attention run", "attention fix", "attention stop", "attention claim",
                     "attention done"), {B, D}),
    "attention check-login": {S},
    "steward run": {L, S},
    **dict.fromkeys(("mine run", "mine status", "mine tasks", "mine backfill-tasks"), {L, S}),
    "canary plant": {L},
    **dict.fromkeys(("case record", "case show", "case list", "case observe", "case receipt", "case index",
                     "case refreeze"), {L}),
    **dict.fromkeys(("statement add", "statement list"), {L}),
    **dict.fromkeys(("grant add", "grant revoke", "grant list"), {L}),
    **dict.fromkeys(("user-model show", "user-model add", "user-model lapse"), {L}),
    "doctor settings": {L},
    **dict.fromkeys(("doctor invocation", "doctor miner", "doctor premises"), {S}),
    **dict.fromkeys(("config get", "config set", "config unset"), {L}),
    "bucket prune": {L}, "proposal validate": {L},
}
# What the switched-on capabilities (ledger, canon) release, spelled out:
# every top-level verb, bare verb and subcommand path that runs on Windows.
# (`index` and `skill` have no bare form: argparse requires their subcommand.)
RELEASED = (BASIC | LEDGER | CANON) - {"index", "skill"} | {
    "host add", "host list", "host rebind", "host remove", "host set-mode", "host commit-drift",
    "link contradicts", "followup done", "followup add", "notice list", "notice done",
    "telemetry note", "telemetry flush", "telemetry read-observed",
    "overseer status", "overseer report", "overseer open", "overseer respond",
    "index status", "index build", "index related", "index groups",
    "skill write", "skill retire", "skill rename", "skill veto", "skill register", "skill unregister",
    "skill list", "skill request build", "skill request change", "skill request withdraw",
    "skill reference show", "skill reference check", "skill reference status",
    "skill script list", "skill script show", "canary plant",
    "case record", "case show", "case list", "case observe", "case receipt", "case index", "case refreeze",
    "statement add", "statement list", "grant add", "grant revoke", "grant list",
    "user-model show", "user-model add", "user-model lapse", "doctor settings",
    "config get", "config set", "config unset", "bucket prune", "proposal validate",
}


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
    assert {k for k, on in cap.AVAILABLE.items() if on} == {"ledger", "canon"}
    for capability, needs_it in expected.items():
        assert {v for v in verbs if capability in cap.REQUIRES[v]} == needs_it
    assert {v for v in verbs if not cap.REQUIRES[v]} == BASIC
    assert {k for k in cap.REQUIRES if k.startswith("teach ")} == {
        "teach --route", "teach --dest", "teach --note", "teach --hook-input", "teach --allow-empty-glob",
        "teach --rules-path", "teach --allow-unpathed", "teach --follow-up", "teach --unblocks-on",
        "teach --follow-up-note",
    }
    assert set(subcommands(choices["host"])) == {"add", "list", "rebind", "commit-drift", "remove", "set-mode"}
    # Every subcommand path is listed, with exactly the needs spelled out above.
    paths = {form for _, form, _ in all_forms(cli._build_parser()) if " " in form}
    listed = {k: set(v) for k, v in cap.REQUIRES.items() if " " in k and not k.startswith("teach ")}
    assert set(listed) == paths == set(SUBFORMS)
    assert listed == SUBFORMS
    # Every form that has subcommands names where argparse keeps the choice.
    parents = {path.rsplit(" ", 1)[0] for path in paths}
    assert set(cap.SUBCOMMANDS) == parents


def all_forms(parser):
    """(argv, form, verb) for every top-level verb, bare verb whose
    subcommand is optional, and subcommand path the real parser accepts."""
    out = []

    def walk(node, path):
        sub = next((a for a in node._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub is None or not sub.required:
            out.append(([*path, *required_arguments(node)], " ".join(path), path[0]))
        if sub is not None:
            for name, child in sub.choices.items():
                walk(child, [*path, name])

    for verb, child in subcommands(parser).items():
        walk(child, [verb])
    return out


def required_arguments(parser):
    """The required arguments of *parser* itself, its subcommands left out."""
    args = []
    grouped = {g._group_actions[0] for g in parser._mutually_exclusive_groups if g.required}
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            continue
        if a.required or a in grouped:
            if a.option_strings:
                args.append(a.option_strings[0])
            if a.nargs != 0:
                args.append(str(next(iter(a.choices))) if a.choices else "1")
    return args


def test_released_forms_are_exactly_the_switched_on_rows(monkeypatch):
    from self_learn.primitives import capabilities as cap

    parser = cli._build_parser()
    released = set()
    for argv, form, verb in all_forms(parser):
        args = parser.parse_args(argv)
        outcome = cap.refused(args)
        assert outcome in (None, verb), (argv, outcome)
        if outcome is None:
            released.add(form)
    assert released == RELEASED
    # teach: an explicit non-hook destination releases the route options; the
    # analyst (no destination), a hook destination and hook input stay off.
    assert cap.refused(parser.parse_args(["teach", "--dest", "claude-md", "--route", "--note", "x"])) is None
    for argv in (["teach", "--route"], ["teach", "--dest", "hook"], ["teach", "--hook-input", "x"]):
        assert cap.refused(parser.parse_args(argv)) == "teach", argv
    assert cap.refused(parser.parse_args(["--selftest"])) == "--selftest"
    # Fail closed: an unlisted verb or subcommand is refused.
    assert cap.refused(argparse.Namespace(command="unlisted", selftest=False)) == "unlisted"
    monkeypatch.delitem(cap.REQUIRES, "doctor settings")
    assert cap.refused(parser.parse_args(["doctor", "settings"])) == "doctor"
    assert cap.hook_destination_refusal("lrn-00000000") == (
        "lrn-00000000: the hook destination is unavailable in Windows capture mode")
    monkeypatch.setitem(cap.AVAILABLE, "hooks", True)
    assert cap.hook_destination_refusal("lrn-00000000") is None


@windows
def test_refusal_profile_precedes_dispatch(tmp_path, monkeypatch, capsys):
    for key, value in scratch_env(tmp_path).items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)

    def forbidden(*args, **kwargs):
        pytest.fail("refusal reached watchdog, provider, child process or selfcheck")

    for module, attr in [(miner, "maybe_kick"), (worker, "kick"), (cli.selfcheck, "run_selftest"),
                         (cli.gitops.procs, "run_command"), (cli.gitops.procs, "run_bounded")]:
        monkeypatch.setattr(module, attr, forbidden)
    parser = cli._build_parser()
    forms = [(argv, verb) for argv, form, verb in all_forms(parser) if form not in RELEASED]
    assert {verb for _, verb in forms} == {"hook", "premises", "worker", "overseer", "skill", "attention",
                                          "ask", "summarise", "steward", "mine", "serve", "doctor"}
    forms += [(["teach", "--route"], "teach"), (["teach", "--hook-input="], "teach"),
              (["teach", "--dest", "hook"], "teach"), (["--selftest"], "--selftest")]
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
import os, sys
from pathlib import Path
from self_learn.cli import main
from self_learn import gitops, hosts, intents, ledger
from unittest.mock import patch
with patch.object(gitops, '_git', wraps=gitops._git) as commands:
    assert main(['init']) == 0
    assert main(['init']) == 0
    assert all('config' not in call.args[1:] for call in commands.call_args_list)
assert ledger.resolve_home() == Path(os.environ['SELF_LEARN_HOME'])
with patch.object(hosts, '_host_add') as add, patch.object(intents, 'ledger_write') as lock:
    assert hosts.host_add(ledger.resolve_home(), 'target', 'project', mode='plain') is add.return_value
    add.assert_called_once_with(ledger.resolve_home(), 'target', 'project', init=False, mode='plain', note=None)
    lock.assert_not_called()
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
    assert (a["receipt"]["status"], a["receipt"]["scope"]) == ("pending", "project")
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
