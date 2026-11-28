"""Guard hooks on native Windows, and one locale for both systems (lane
w5-activation).

Windows has no Bash to run a generated guard. There, ``hook activate`` writes
the guard's rule file (``hook_rules``) where Linux places the symlink, and
registers it in exec form: Claude Code spawns ``self-learn-hook.exe evaluate
--rule <file>`` directly. The Windows tests drive the real verbs through
``cli.main`` against a scratch profile, ledger, skills root and Claude folder
(a space and a non-ASCII letter in each), with the capability gate opened for
the ledger, canon and hooks only, and seed a hook-routed record the way a
ledger shared with Linux holds one (routing a hook needs grep and a Bash
replay, which are another lane's on Windows).

Decision 180: the generated Bash script pins ``LC_ALL=C.UTF-8`` so it decides
as the evaluator does under any caller locale. The Linux differentials check
that under ``en_US.UTF-8`` and ``C`` (skipped, visibly, when the host lacks
one), the fail-closed branch on a host without the locale, and that a guard
the previous emitter wrote is recognised as such, never as hand-edited.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import pytest

from self_learn import cli, hook_activation, hook_compiler, hook_rules, selfcheck, settings, verbs
from self_learn.hook_compiler import previous_emitter_script, script_for_hook, script_name
from self_learn.ledger_ops import create_record
from self_learn.records import Record

LINUX = sys.platform.startswith("linux")
LINUX_REASON = "Linux differential: runs the generated Bash script"
WINDOWS_REASON = "native Windows activation"
linux = pytest.mark.skipif(not LINUX, reason=LINUX_REASON)
windows = pytest.mark.skipif(os.name != "nt", reason=WINDOWS_REASON)

RID = "lrn-5a5e00a1"
TRIGGER = "About to run a guarded thing"

DENY = {"tools": ["Bash"], "path_regex": r"(^|[;&|[:space:]])rm[[:space:]]+-rf",
        "deny_message": "never rm -rf here"}
DENY_EXAMPLES = {
    "allow": [{"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
              {"tool_name": "Bash", "tool_input": {"command": "rm -i notes.txt"}}],
    "deny": [{"tool_name": "Bash", "tool_input": {"command": "rm -rf /x"}},
             {"tool_name": "Bash", "tool_input": {"command": "cd /tmp && rm  -rf build"}}],
}
WARN = {"mode": "warn", "event": "PostToolUse", "tools": ["Edit", "Write"],
        "path_regex": r"\.storage/", "warn_message": "HA rewrites .storage on shutdown"}
WARN_EXAMPLES = {
    "allow": [{"tool_name": "Edit", "tool_input": {"file_path": "C:\\x\\configuration.yaml"}},
              {"tool_name": "Write", "tool_input": {"file_path": "/y/notes.md"}}],
    "warn": [{"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}},
             {"tool_name": "Edit", "tool_input": {"file_path": "C:\\ha\\.storage/core.config"}}],
}
#: ``\d`` is a stray backslash: grep reads it as ``d``, the evaluator refuses it.
REFUSED = {"tools": ["Bash"], "path_regex": r"curl[[:space:]]+\d", "deny_message": "no"}


def _payload(tool: str, field: str, value: str) -> bytes:
    return json.dumps({"tool_name": tool, "tool_input": {field: value}}).encode("utf-8")


# ============================================ the evaluate program, both systems


def _program() -> Path:
    if os.name == "nt":
        return hook_activation.hook_program()
    return Path(sysconfig.get_path("scripts")) / "self-learn-hook"


def _rule_file(tmp_path: Path, block: dict, examples: dict | None = None) -> Path:
    art = hook_compiler.rule_artifact_for_hook(RID, TRIGGER, block, examples)
    path = tmp_path / f"rule {len(list(tmp_path.glob('*.json')))} é.rule.json"
    path.write_bytes(hook_rules.dumps_rule(art))
    return path


def _evaluate(rule: Path, data: bytes) -> tuple[int, bytes, bytes]:
    proc = subprocess.run([str(_program()), "evaluate", "--rule", str(rule)], input=data,
                          capture_output=True, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


def test_evaluate_program_deny_warn_allow(tmp_path):
    """The installed console script, run as a child the way Claude Code runs
    an exec-form hook: deny = exit 2 with the message on stderr; warn = the
    structured line on stdout, exit 0; allow = silence, exit 0."""
    assert _program().is_file(), _program()
    deny = _rule_file(tmp_path, DENY)
    warn = _rule_file(tmp_path, WARN)
    assert _evaluate(deny, _payload("Bash", "command", "rm -rf /tmp/x")) == (
        2, b"", f"self-learn {RID}: never rm -rf here\n".encode())
    assert _evaluate(deny, _payload("Bash", "command", "ls -la")) == (0, b"", b"")
    assert _evaluate(deny, _payload("Read", "file_path", "rm -rf")) == (0, b"", b"")
    assert _evaluate(deny, b"") == (
        2, b"", f"self-learn {RID}: empty hook input — failing closed\n".encode())
    line = hook_compiler.warn_output("PostToolUse", RID, WARN["warn_message"]) + "\n"
    assert _evaluate(warn, _payload("Edit", "file_path", "C:\\ha\\.storage/core")) == (
        0, line.encode("utf-8"), b"")
    assert _evaluate(warn, _payload("Edit", "file_path", "C:\\ha\\config.yaml")) == (0, b"", b"")


def test_evaluate_program_fails_closed_on_an_unusable_rule(tmp_path):
    """A deny rule that cannot be read or loaded blocks with a line naming
    it; one that declares itself a warning stays silent."""
    deny = _rule_file(tmp_path, DENY)
    warn = _rule_file(tmp_path, WARN)
    call = _payload("Bash", "command", "ls")
    missing = tmp_path / "gone.rule.json"
    rc, out, err = _evaluate(missing, call)
    assert (rc, out) == (2, b"") and b"cannot be used" in err and "failing closed".encode() in err
    for path in (deny, warn):  # a hand edit breaks the digest
        data = json.loads(path.read_bytes())
        data["message"] = data["message"] + " (edited)"
        path.write_bytes(json.dumps(data).encode())
    rc, out, err = _evaluate(deny, call)
    assert (rc, out) == (2, b"")
    assert err.startswith(f"self-learn {RID}: guard rule ".encode()) and b"digest" in err
    assert _evaluate(warn, _payload("Edit", "file_path", "/a/.storage/x")) == (0, b"", b"")
    junk = tmp_path / "junk.rule.json"
    junk.write_bytes(b"not json")
    rc, out, err = _evaluate(junk, call)
    assert (rc, out) == (2, b"") and err.startswith(b"self-learn: guard rule ")


def test_evaluate_program_is_fast_and_loads_no_ledger_or_sdk(tmp_path):
    """The hook runs on every matching call under a 5 s limit: measure the
    program's start-to-decision time, and check the evaluate path imports
    no ledger, CLI or SDK module (positive control: it did load the rules)."""
    deny = _rule_file(tmp_path, DENY)
    data = _payload("Bash", "command", "rm -rf /x")
    times = []
    for _ in range(5):
        start = time.perf_counter()
        assert _evaluate(deny, data)[0] == 2
        times.append(time.perf_counter() - start)
    times.sort()
    print(f"self-learn-hook evaluate wall time: min {times[0]:.3f}s median {times[2]:.3f}s "
          f"max {times[-1]:.3f}s")
    assert times[-1] < 5.0
    probe = (
        "import sys\n"
        "from self_learn import hook_entry\n"
        f"rc = hook_entry._evaluate(['--rule', {str(deny)!r}])\n"
        "mods = sorted(m for m in sys.modules if m.split('.')[0] in ('self_learn', 'claude_agent_sdk'))\n"
        "print(rc, ' '.join(mods))\n"
    )
    proc = subprocess.run([sys.executable, "-c", probe], input=data, capture_output=True, timeout=60)
    rc, mods = proc.stdout.decode().split(" ", 1)
    loaded = set(mods.split())
    assert rc == "2" and "self_learn.hook_rules" in loaded, proc
    forbidden = {"self_learn.ledger", "self_learn.ledger_ops", "self_learn.records", "self_learn.verbs",
                 "self_learn.cli", "self_learn.hook_compiler", "claude_agent_sdk"}
    assert not loaded & forbidden, sorted(loaded & forbidden)


# ======================================= decision 180: the locale pin (Linux)


_TOOLS = ("bash", "jq", "grep", "cat", "awk")


@pytest.fixture(scope="module")
def tool_bin(tmp_path_factory) -> Path:
    missing = [t for t in _TOOLS if shutil.which(t) is None]
    if missing:
        pytest.skip(f"the generated scripts need {missing} on PATH")
    bindir = tmp_path_factory.mktemp("bin")
    for tool in _TOOLS:
        os.symlink(shutil.which(tool), bindir / tool)
    return bindir


def _locales() -> set[str]:
    out = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()
    return {name.lower().replace("utf-8", "utf8") for name in out}


def _have(locale: str) -> bool:
    return locale == "C" or locale.lower().replace("utf-8", "utf8") in _locales()


def _run_script(tool_bin: Path, script: Path, data: bytes, locale: str) -> tuple[int, bytes, str]:
    env = {"PATH": str(tool_bin), "LC_ALL": locale}
    proc = subprocess.run([str(tool_bin / "bash"), str(script)], input=data, capture_output=True,
                          env=env, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


#: Patterns whose answer depended on the caller's locale before the pin,
#: and texts with accented letters and multibyte characters.
LOCALE_PATTERNS = (r"^[a-z]+$", r"^..$", r"^.$", r"^[^a-z]$", r"[[:alpha:]]{3}", r"caf.$")
LOCALE_TEXTS = ("é", "abc", "café", "cafés", "ß", "日本", "Ωmega", "naïve", "a", "é1")


@linux
@pytest.mark.parametrize("caller", ["en_US.UTF-8", "C"])
def test_the_pinned_script_decides_as_the_evaluator_under_the_callers_locale(
        tool_bin, tmp_path, caller):
    """Every pattern and text, deny and warn, as a command and as a path:
    the script run under the caller's locale gives exactly the decision it
    gives under C.UTF-8 and the evaluator's."""
    if not _have(caller):
        pytest.skip(f"this host has no {caller} locale (locale -a)")
    assert _have("C.UTF-8"), "C.UTF-8 is the pinned locale"
    work = []
    for n, pattern in enumerate(LOCALE_PATTERNS):
        for mode in ("deny", "warn"):
            text = hook_compiler.generate_script(RID, TRIGGER, ["Bash", "Edit"], pattern, "m",
                                                 mode=mode)
            rule = hook_rules.load_rule(hook_compiler.rule_artifact(
                RID, TRIGGER, ["Bash", "Edit"], pattern, "m", mode=mode))
            script = tmp_path / f"g{n}{mode}.sh"
            script.write_text(text, encoding="utf-8")
            for value in LOCALE_TEXTS:
                for tool, field in (("Bash", "command"), ("Edit", "file_path")):
                    work.append((pattern, mode, value, tool, script, rule,
                                 _payload(tool, field, value)))

    def one(row):
        pattern, mode, value, tool, script, rule, data = row
        pinned = _run_script(tool_bin, script, data, "C.UTF-8")
        theirs = _run_script(tool_bin, script, data, caller)
        got = hook_rules.evaluate(rule, data)
        mine = (got.exit_code, got.stdout, got.stderr)
        if not (theirs == pinned == mine):
            return f"{pattern!r} {mode} {tool} {value!r}: {caller} {theirs} C.UTF-8 {pinned} evaluator {mine}"
        return None

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        diffs = [d for d in pool.map(one, work) if d]
    assert diffs == []
    assert len(work) == len(LOCALE_PATTERNS) * 2 * len(LOCALE_TEXTS) * 2


@linux
@pytest.mark.parametrize("caller", ["en_US.UTF-8", "C"])
def test_without_the_pin_the_callers_locale_changes_the_decision(tool_bin, tmp_path, caller):
    """Positive control for the test above: the previous emitter's script
    (the pin removed) does decide differently under the caller's locale."""
    if not _have(caller):
        pytest.skip(f"this host has no {caller} locale (locale -a)")
    pattern = r"^[a-z]$" if caller == "en_US.UTF-8" else r"^..$"
    current = hook_compiler.generate_script(RID, TRIGGER, ["Bash"], pattern, "m")
    old = previous_emitter_script(current, RID, "deny")
    assert old is not None
    script = tmp_path / "old.sh"
    script.write_text(old, encoding="utf-8")
    data = _payload("Bash", "command", "é")
    assert _run_script(tool_bin, script, data, "C.UTF-8")[0] == 0
    assert _run_script(tool_bin, script, data, caller)[0] == 2  # the gap the pin closes


@linux
def test_a_host_without_the_pinned_locale_fails_closed_or_stays_silent(tool_bin, tmp_path):
    """The script must not assume the pin took: with a locale that does not
    exist, a deny guard blocks every call with its matcher-failure line, a
    warning stays silent, and bash's own setlocale warning never reaches
    stderr."""
    rows = []
    for mode in ("deny", "warn"):
        text = hook_compiler.generate_script(RID, TRIGGER, ["Bash"], r"^rm ", "m", mode=mode)
        assert text.count("export LC_ALL=C.UTF-8 2>/dev/null\n") == 1
        good = tmp_path / f"{mode}-good.sh"
        good.write_text(text, encoding="utf-8")
        bad = tmp_path / f"{mode}-bad.sh"
        bad.write_text(text.replace("LC_ALL=C.UTF-8", "LC_ALL=xx_XX.UTF-8"), encoding="utf-8")
        rows.append((mode, good, bad))
    match, miss = _payload("Bash", "command", "rm x"), _payload("Bash", "command", "ls")
    (_, dgood, dbad), (_, wgood, wbad) = rows
    # controls: the pinned scripts decide normally
    assert _run_script(tool_bin, dgood, match, "C")[0] == 2
    assert _run_script(tool_bin, dgood, miss, "C") == (0, b"", "")
    assert _run_script(tool_bin, wgood, match, "C")[1] != b""
    failed = f"self-learn {RID}: guard regex failed — failing closed\n"
    assert _run_script(tool_bin, dbad, match, "C") == (2, b"", failed)
    assert _run_script(tool_bin, dbad, miss, "C") == (2, b"", failed)
    assert _run_script(tool_bin, wbad, match, "C") == (0, b"", "")


# -------------------------------- a guard the previous emitter wrote (Linux)


@pytest.fixture
def route_env(tmp_path, monkeypatch):
    from test_route_hook import Env

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    env = Env(tmp_path)
    env.claude = claude
    return env


def _route_with_previous_emitter(env, monkeypatch, block: dict | None, examples: dict | None):
    from test_route_hook import RID as ROUTE_RID
    from test_route_hook import TRIGGER as ROUTE_TRIGGER
    from test_route_hook import seed_hook

    overrides = {} if block is None else {"hook": block, "examples": examples}
    with monkeypatch.context() as m:
        m.setattr(hook_compiler, "_locale_pin", lambda record_id, mode: "")
        seed_hook(env, **overrides)
        verbs.route(env.home, ROUTE_RID)
    record = Record.from_path(env.resolved())
    meta = record.routing["hook"]
    current = script_for_hook(ROUTE_RID, ROUTE_TRIGGER, meta)
    assert meta["script"] != current  # control: the current emitter differs
    assert previous_emitter_script(current, ROUTE_RID, hook_compiler.hook_mode(meta)) == meta["script"]
    return ROUTE_RID, env.host / meta["script_path"], current


@linux
def test_a_warn_hook_from_the_previous_emitter_is_regenerated_not_hand_edited(route_env, monkeypatch):
    """The S-133 mechanism, unchanged: recompile regenerates an outdated
    warning hook whose placed file holds its stored bytes, so the previous
    emitter's warning hooks get the pin; none is reported hand-edited."""
    rid, script, current = _route_with_previous_emitter(route_env, monkeypatch, WARN, WARN_EXAMPLES)
    assert verbs.stale_warn_hooks(route_env.home) == ([rid], {})
    result = verbs.recompile(route_env.home, no_push=True)
    assert result.hooks_regenerated == [rid]
    assert not [w for w in result.warnings if verbs.WARN_HOOK_HAND_EDITED in w]
    assert script.read_text(encoding="utf-8") == current
    assert "export LC_ALL=C.UTF-8" in current
    assert selfcheck._check_hooks(route_env.home, route_env.claude)[0] is selfcheck.Verdict.PASS


@linux
def test_a_deny_guard_from_the_previous_emitter_keeps_its_approved_bytes(route_env, monkeypatch):
    """M3-2 as written for deny guards: never regenerated, never flagged.
    The doctor passes it and recompile leaves it, with no hand-edit report."""
    rid, script, current = _route_with_previous_emitter(route_env, monkeypatch, None, None)
    stored = Record.from_path(route_env.resolved()).routing["hook"]["script"]
    assert selfcheck._check_hooks(route_env.home, route_env.claude)[0] is selfcheck.Verdict.PASS
    result = verbs.recompile(route_env.home, no_push=True)
    assert result.hooks_regenerated == [] and result.hooks_refused == {}
    assert not [w for w in result.warnings if rid in w]
    assert script.read_text(encoding="utf-8") == stored != current


# =================================================== native Windows activation


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=60).stdout


class Win:
    """A scratch profile, ledger, skills root and Claude folder; the ledger,
    canon and hooks capabilities open."""

    def __init__(self, root: Path, monkeypatch, capsys):
        from self_learn.primitives import capabilities

        self.root, self.capsys, self.monkeypatch = root, capsys, monkeypatch
        self.profile = root / "prof été"
        self.profile.mkdir(parents=True)
        self.claude = root / "claude été"
        (self.claude / "hooks").mkdir(parents=True)
        for key in ("CLAUDE_CONFIG_DIR", "PYTHONUTF8", *settings.AGENT_CALLER_MARKERS):
            monkeypatch.delenv(key, raising=False)
        env = {
            "USERPROFILE": self.profile, "HOME": self.profile, "SELF_LEARN_CLAUDE_DIR": self.claude,
            "SELF_LEARN_HOME": root / "ledger", "XDG_CACHE_HOME": root / "cache",
            "GIT_CONFIG_GLOBAL": self.profile / "gitconfig",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        drive, rest = os.path.splitdrive(str(self.profile))
        monkeypatch.setenv("HOMEDRIVE", drive)
        monkeypatch.setenv("HOMEPATH", rest)
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
        for role in ("AUTHOR", "COMMITTER"):
            monkeypatch.setenv(f"GIT_{role}_NAME", "Hook Test")
            monkeypatch.setenv(f"GIT_{role}_EMAIL", "hooks@example.invalid")
        monkeypatch.setenv("SELF_LEARN_ACTOR", "hook-test")
        subprocess.run(["git", "config", "--global", "core.autocrlf", "true"], check=True, timeout=30)
        for cap in ("ledger", "canon", "hooks"):
            monkeypatch.setitem(capabilities.AVAILABLE, cap, True)
        self.ledger = root / "ledger"
        self.run("init")
        self.skills = root / "skills root"
        skill = self.skills / "plugins" / "s-plugin" / "skills" / "s"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_bytes(b"---\nname: s\ndescription: seeded skill\n---\n\n# s\n")
        market = self.skills / ".claude-plugin" / "marketplace.json"
        market.parent.mkdir()
        market.write_text(json.dumps({"name": "skills", "owner": {"name": "t"}, "plugins": [
            {"name": "s-plugin", "source": "./plugins/s-plugin", "description": "p",
             "version": "1.0.0"}]}, indent=2) + "\n", encoding="utf-8")
        git(self.skills, "init", "-q")
        git(self.skills, "config", "core.autocrlf", "false")
        git(self.skills, "add", "--", ".claude-plugin/marketplace.json", "plugins/s-plugin/skills/s/SKILL.md")
        git(self.skills, "commit", "-q", "-m", "seed")
        self.run("host", "add", str(self.skills), "--skills-root")

    @property
    def settings(self) -> Path:
        return self.claude / "settings.json"

    def code(self, *argv: str) -> tuple[int, str, str]:
        rc = cli.main(list(argv))
        out = self.capsys.readouterr()
        return rc, out.out, out.err

    def run(self, *argv: str) -> str:
        rc, out, err = self.code(*argv)
        assert rc == 0, (argv, rc, out, err)
        return out + err

    def seed(self, rid: str, block: dict, examples: dict | None, *, previous: bool = False) -> Path:
        """A hook-routed record, as a ledger routed on Linux holds it: the
        approved script in the skills root (no execute bit here) and the
        record in ``resolved/`` with its routing block."""
        from support import make_behavior

        script = script_for_hook(rid, TRIGGER, block)
        if previous:
            script = previous_emitter_script(script, rid, hook_compiler.hook_mode(block))
            assert script is not None
        name = script_name(rid, TRIGGER)
        rel = f"plugins/s-plugin/hooks/{name}"
        target = self.skills / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(script.encode("utf-8"))
        git(self.skills, "add", "--", rel)
        git(self.skills, "commit", "-q", "-m", f"seed {rid}")
        pending = create_record(self.ledger, make_behavior(scope="skill:s", record_id=rid, trigger=TRIGGER))
        record = Record.from_path(pending)
        record.set_status("routed")
        record.set_routing({"routed_at": "2026-11-28T00:00:00Z", "destination": "hook", "by": "analyst",
                            "hook": verbs._hook_route_meta(block, rel, script, examples or {})})
        resolved = pending.parent.parent / "resolved" / pending.name
        resolved.parent.mkdir(exist_ok=True)
        record.write(resolved)
        pending.unlink()
        git(self.ledger, "add", "-A")
        git(self.ledger, "commit", "-q", "-m", f"seed {rid}")
        return target

    def rule(self, rid: str) -> Path:
        return self.claude / "hooks" / hook_activation.rule_file_name(script_name(rid, TRIGGER))

    def snapshot(self) -> dict[str, bytes]:
        return {p.relative_to(self.claude).as_posix(): p.read_bytes()
                for p in sorted(self.claude.rglob("*")) if p.is_file()}

    def doctor(self) -> tuple[selfcheck.Verdict, str]:
        return selfcheck._check_hooks(self.ledger, self.claude)


@pytest.fixture
def win(tmp_path, monkeypatch, capsys):
    return Win(tmp_path.resolve(), monkeypatch, capsys)


def _entry(win: Win, rid: str, mode: str) -> dict:
    return hook_activation.rule_hook_entry(hook_activation.hook_program(), win.rule(rid), mode)


def _handlers(win: Win, event: str) -> list[dict]:
    data = json.loads(win.settings.read_bytes().decode("utf-8-sig"))
    return [h for item in data.get("hooks", {}).get(event, []) for h in item["hooks"]]


FOREIGN = {
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "C:\\tools\\other guard.exe", "args": ["--check"]}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}],
    },
}


def _seed_settings(win: Win, *, crlf: bool = False, bom: bool = False) -> bytes:
    text = json.dumps(FOREIGN, indent=2) + "\n"
    data = (b"\xef\xbb\xbf" if bom else b"") + (text.replace("\n", "\r\n") if crlf else text).encode()
    win.settings.write_bytes(data)
    return data


@windows
def test_windows_activate_writes_the_rule_and_an_exec_form_entry(win):
    script = win.seed(RID, DENY, DENY_EXAMPLES)
    assert not script.stat().st_mode & 0o100  # no execute bit on Windows ...
    verdict, message = win.doctor()  # ... and the doctor does not call that broken
    assert verdict is selfcheck.Verdict.PASS, message
    assert "1 live hook script(s) intact; 0 rule(s) active" in message
    out = win.run("hook", "activate", RID, "--no-push")
    assert "replayed clean through the rule evaluator" in out
    rule = hook_rules.load_rule(win.rule(RID).read_bytes())
    assert (rule.record_id, rule.mode) == (RID, "deny")
    entry = _handlers(win, "PreToolUse")
    assert entry == [_entry(win, RID, "deny")]
    assert entry[0]["command"].endswith("self-learn-hook.exe") and Path(entry[0]["command"]).is_file()
    assert entry[0]["args"] == ["evaluate", "--rule", str(win.rule(RID))]
    assert (entry[0]["timeout"], entry[0]["onFailure"]) == (5, "block")
    verdict, message = win.doctor()
    assert verdict is selfcheck.Verdict.PASS and "1 rule(s) active on this machine" in message
    history = Record.from_path(next(win.ledger.rglob(f"resolved/{RID}.md"))).history
    assert history[-1]["event"] == "hook-activated"
    # The registered entry works as Claude Code spawns it: no shell.
    run = lambda data: subprocess.run([entry[0]["command"], *entry[0]["args"]], input=data,  # noqa: E731
                                      capture_output=True, timeout=30)
    blocked = run(json.dumps(DENY_EXAMPLES["deny"][0]).encode())
    assert (blocked.returncode, blocked.stdout, blocked.stderr) == (
        2, b"", f"self-learn {RID}: never rm -rf here\n".encode())
    allowed = run(json.dumps(DENY_EXAMPLES["allow"][0]).encode())
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")


@windows
def test_windows_reactivate_changes_nothing(win):
    win.seed(RID, DENY, DENY_EXAMPLES)
    _seed_settings(win)
    win.run("hook", "activate", RID, "--no-push")
    before = win.snapshot()
    head = git(win.ledger, "rev-parse", "HEAD")
    out = win.run("hook", "activate", RID, "--no-push")
    assert "already holds this rule" in out and "already registered (idempotent)" in out
    assert win.snapshot() == before  # no new backup, same rule, same settings
    assert git(win.ledger, "rev-parse", "HEAD") != head  # the receipt still commits


@windows
def test_windows_deactivate_removes_exactly_our_entry_and_rule(win):
    win.seed(RID, WARN, WARN_EXAMPLES)
    seed = _seed_settings(win)
    win.run("hook", "activate", RID, "--no-push")
    assert _handlers(win, "PostToolUse") == [_entry(win, RID, "warn")]
    assert "onFailure" not in _entry(win, RID, "warn")  # a warning never blocks
    assert win.rule(RID).is_file()
    win.run("hook", "deactivate", RID, "--no-push")
    assert win.settings.read_bytes() == seed
    assert not win.rule(RID).exists()
    again = win.run("hook", "deactivate", RID, "--no-push")
    assert "already absent (idempotent)" in again


@windows
def test_windows_foreign_entries_are_left_alone(win):
    win.seed(RID, DENY, DENY_EXAMPLES)
    _seed_settings(win)
    win.run("hook", "activate", RID, "--no-push")
    data = json.loads(win.settings.read_bytes())
    assert data["permissions"] == FOREIGN["permissions"]
    assert data["hooks"]["SessionStart"] == FOREIGN["hooks"]["SessionStart"]
    assert data["hooks"]["PreToolUse"][0] == FOREIGN["hooks"]["PreToolUse"][0]
    assert len(data["hooks"]["PreToolUse"]) == 2
    backups = list(win.claude.glob("settings.json.self-learn-bak.*"))
    assert len(backups) == 1 and json.loads(backups[0].read_bytes()) == FOREIGN
    win.run("hook", "deactivate", RID, "--no-push")
    assert json.loads(win.settings.read_bytes()) == FOREIGN


@windows
@pytest.mark.parametrize("edit", ["timeout", "matcher", "event"])
def test_windows_a_hand_edited_entry_is_refused(win, edit):
    win.seed(RID, DENY, DENY_EXAMPLES)
    win.run("hook", "activate", RID, "--no-push")
    data = json.loads(win.settings.read_bytes())
    if edit == "timeout":
        data["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 30
    elif edit == "matcher":
        data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|Edit"
    else:
        data["hooks"]["PostToolUse"] = data["hooks"].pop("PreToolUse")
    win.settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    before = win.snapshot()
    for verb in ("activate", "deactivate"):
        rc, out, err = win.code("hook", verb, RID, "--no-push")
        assert rc == 1, (verb, out, err)
        marker = {"timeout": "its timeout", "matcher": "matcher 'Bash|Edit'",
                  "event": "under PostToolUse, expected PreToolUse"}[edit]
        assert "self-learn did not write" in err and marker in err, err
        assert win.snapshot() == before


@windows
def test_windows_a_hand_edited_rule_file_is_refused(win):
    win.seed(RID, DENY, DENY_EXAMPLES)
    win.run("hook", "activate", RID, "--no-push")
    data = json.loads(win.rule(RID).read_bytes())
    data["match"]["pattern"] = "nothing-matches-this"
    win.rule(RID).write_text(json.dumps(data), encoding="utf-8")
    before = win.snapshot()
    rc, _, err = win.code("hook", "activate", RID, "--no-push")
    assert rc == 1 and "is not a rule self-learn wrote" in err, err
    assert win.snapshot() == before
    verdict, message = win.doctor()
    assert verdict is selfcheck.Verdict.FAIL and "does not load" in message


@windows
def test_windows_a_refused_pattern_is_reported_and_nothing_written(win):
    win.seed(RID, REFUSED, None)
    good = "lrn-5a5e00a2"
    win.seed(good, DENY, DENY_EXAMPLES)
    verdict, message = win.doctor()
    assert verdict is selfcheck.Verdict.PASS, message
    assert f"{RID}: inactive on this machine — " in message and "stray" in message.lower()
    before = win.snapshot()
    rc, out, err = win.code("hook", "activate", RID, "--no-push")
    assert rc == 1 and "this guard cannot run on Windows: " in err, (out, err)
    assert win.snapshot() == before and not win.settings.exists()
    win.run("hook", "activate", good, "--no-push")  # positive control: a buildable guard activates
    verdict, message = win.doctor()
    assert verdict is selfcheck.Verdict.PASS and "1 rule(s) active" in message
    assert f"{RID}: inactive on this machine" in message


@windows
@pytest.mark.parametrize("form", ["crlf", "bom", "crlf-bom"])
def test_windows_settings_keep_their_line_endings_and_bom(win, form):
    win.seed(RID, DENY, DENY_EXAMPLES)
    seed = _seed_settings(win, crlf="crlf" in form, bom="bom" in form)
    win.run("hook", "activate", RID, "--no-push")
    data = win.settings.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf") == ("bom" in form)
    if "crlf" in form:
        assert b"\n" not in data.replace(b"\r\n", b"")
    parsed = json.loads(data.decode("utf-8-sig"))
    assert parsed["hooks"]["PreToolUse"][1]["hooks"] == [_entry(win, RID, "deny")]
    win.run("hook", "deactivate", RID, "--no-push")
    assert win.settings.read_bytes() == seed


@windows
@pytest.mark.parametrize("fails", ["settings.json", "rule"])
def test_windows_a_failed_write_rolls_back_everything(win, monkeypatch, fails):
    from self_learn.primitives import fsops

    win.seed(RID, DENY, DENY_EXAMPLES)
    seed = _seed_settings(win)
    before = win.snapshot()
    head = git(win.ledger, "rev-parse", "HEAD")
    target = "settings.json" if fails == "settings.json" else win.rule(RID).name
    real = fsops.atomic_write
    hits = []

    def failing(path, data, **kw):
        if Path(path).name == target:
            hits.append(path)
            raise OSError(28, "injected: no space left on device", str(path))
        return real(path, data, **kw)

    monkeypatch.setattr(fsops, "atomic_write", failing)
    with pytest.raises(OSError, match="injected"):
        verbs.hook_activate(win.ledger, RID, no_push=True)
    assert hits  # the injection reached the real write
    assert win.snapshot() == before and win.settings.read_bytes() == seed
    assert git(win.ledger, "rev-parse", "HEAD") == head


@windows
def test_windows_a_missing_hook_program_refuses_and_writes_nothing(win, monkeypatch):
    win.seed(RID, DENY, DENY_EXAMPLES)
    gone = win.root / "no venv" / "Scripts" / "self-learn-hook.exe"
    monkeypatch.setattr(hook_activation, "hook_program", lambda: gone)
    before = win.snapshot()
    rc, _, err = win.code("hook", "activate", RID, "--no-push")
    assert rc == 1 and f"cannot find self-learn-hook.exe at {gone}" in err, err
    assert win.snapshot() == before and not win.settings.exists()


@windows
def test_windows_a_guard_from_the_previous_emitter_activates(win):
    """A deny guard routed on Linux before the locale pin (its approved bytes
    are the previous emitter's) is recognised as such and activates."""
    win.seed(RID, DENY, DENY_EXAMPLES, previous=True)
    out = win.run("hook", "activate", RID, "--no-push")
    assert "previous emitter's" in out
    assert win.doctor()[0] is selfcheck.Verdict.PASS
