"""Compare the installed hook commands with the Bash hooks and fixture bytes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dataclasses import dataclass

import pytest

import self_learn


HOOKS = Path(__file__).resolve().parents[2] / "hooks"
BASH_HOOKS = {
    "session-start": "self-learn-pending.sh",
    "read-observed": "self-learn-refread.sh",
}
WINDOWS = sys.platform == "win32"
NOTICE_HEADER = (
    "self-learn notices for this project — yours to carry out in this session "
    "(no sudo needed): do it, then `self-learn notice done <id>`\n"
)
DEGRADED = "⚠️  self-learn: pending-count check skipped — "
READ_PATH = "/work/references/guide.md"


def event(path=READ_PATH, **fields):
    return payload({"tool_input": {"file_path": path}, **fields})


def payload(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class Case:
    name: str
    command: str
    stdin: bytes
    stdout: str = ""
    args: tuple[str, ...] | None = None
    child_output: bytes = b""
    child_exit: int = 0
    slow: bool = False
    missing: str = ""

    def expected(self):
        invocations = []
        if self.args is not None:
            stdin = self.stdin if self.command == "session-start" else b""
            invocations.append([list(self.args), stdin.hex()])
        return (self.stdout.encode("utf-8"), 0, invocations, bool(self.args) and not self.slow)


def status(name, stdin=b"{}", *, missing="", **kwargs):
    args = None if missing else ("status", "--fast")
    return Case(name, "session-start", stdin, args=args, missing=missing, **kwargs)


def read(name, stdin, *, path=None, session="", subagent=False, **kwargs):
    args = None
    if path is not None:
        args = ("telemetry", "read-observed", "--path", path, "--session", session)
        if subagent:
            args += ("--subagent",)
    return Case(name, "read-observed", stdin, args=args, **kwargs)


CASES = [
    status("status-healthy", b'{"session_id":"parent"}\n', child_output=b'{"home_state":"ok"}'),
    status("status-empty-event", b"", child_output=b"{}"),
    status("status-malformed-event", b'{broken\x00\n', child_output=b'{"total_unreadable":1}',
           stdout="⚠️  self-learn: 1 unreadable record(s) in the queue — `self-learn status` names them\n"),
    status("status-empty-output"),
    status("status-malformed-output", child_output=b'{"total_unreadable": 1} invalid'),
    status("status-failure", child_exit=7),
    status("status-home", child_exit=5, child_output=payload({
        "home_state": "missing", "home": "/work/ledger", "total_unreadable": 2,
    }), stdout=(
        "⚠️  self-learn: ledger home /work/ledger is missing — no records are visible "
        "(this is NOT an empty ledger). Check $SELF_LEARN_HOME or clone/bootstrap the ledger repo; "
        "`self-learn status` explains.\n"
    )),
    status("status-home-fallback", child_output=b'{"home_state":"broken"}', stdout=(
        "⚠️  self-learn: ledger home ? is broken — no records are visible "
        "(this is NOT an empty ledger). Check $SELF_LEARN_HOME or clone/bootstrap the ledger repo; "
        "`self-learn status` explains.\n"
    )),
    status("status-warnings", child_output=payload({
        "home_state": False, "intents_probe": "error", "intents_stopped_count": 2,
        "intents_stopped": ["first", "second"], "total_unreadable": 3,
        "project_notices": [{"line": "check café"}, {}, {"line": "check another\n"}],
        "project_notices_more": 1, "total_pending": 99, "worker_stale": True,
    }), stdout=(
        "⚠️ self-learn: could not probe the ledger lock — a STOPPED intent may be hidden; "
        "run `self-learn status`\n"
        "🛑 self-learn: 2 STOPPED transaction intents (first, second) — every ledger write refuses "
        "until cleared. Run `self-learn reconcile --clear-intent first` after inspecting the offender.\n"
        "⚠️  self-learn: 3 unreadable record(s) in the queue — `self-learn status` names them\n"
        + NOTICE_HEADER + "check café\ncheck another\n"
        "self-learn: 1 more notice(s) for this project — self-learn notice list\n"
    )),
    status("status-fallbacks", child_output=payload({
        "intents_stopped_count": "01", "intents_stopped": "invalid",
        "total_unreadable": -1, "project_notices": [{"line": "valid"}, 7],
        "project_notices_more": 2,
    }), stdout=(
        "🛑 self-learn: 01 STOPPED transaction intent (?) — every ledger write refuses until "
        "cleared. Run `self-learn reconcile --clear-intent ?` after inspecting the offender.\n"
    )),
    status("status-empty-ids", child_output=b'{"intents_stopped_count":1}', stdout=(
        "🛑 self-learn: 1 STOPPED transaction intent () — every ledger write refuses until "
        "cleared. Run `self-learn reconcile --clear-intent ?` after inspecting the offender.\n"
    )),
    status("status-notice-no-more", child_output=payload({"project_notices": [{"line": "one"}]}),
           stdout=NOTICE_HEADER + "one\n"),
    status("status-absent", missing="self-learn", stdout=DEGRADED + "self-learn is not on PATH\n"),
    status("status-exit-124", child_exit=124, child_output=b'{"total_unreadable":1}',
           stdout=DEGRADED + "self-learn status timed out after 4s\n"),
    status("status-slow", slow=True, stdout=DEGRADED + "self-learn status timed out after 4s\n"),
    read("read-observed", event(session_id="parent", tool_response={"content": "private"}),
         path=READ_PATH, session="parent", child_output=b"ignored child stdout"),
    read("read-agent-key-null", event(agent_id=None, session_id="parent"),
         path=READ_PATH, session="parent", subagent=True),
    read("read-agent-key-false", event(agent_id=False), path=READ_PATH, subagent=True),
    read("read-missing-session", event(), path=READ_PATH),
    read("read-missing-tool-input", b'{"session_id":"parent"}'),
    read("read-missing-file-path", b'{"tool_input":{}}'),
    read("read-malformed", event() + b" {invalid"),
    read("read-empty", b""),
    read("read-outside", event("/work/reference/guide.md")),
    read("read-wrong-suffix", event("/work/references/guide.txt")),
    read("read-wrong-case", event("/work/references/guide.MD")),
    read("read-no-leading-slash", event("references/guide.md")),
    read("read-nested", event("/work/references/nested/.md"), path="/work/references/nested/.md"),
    read("read-unusual", event('/work/references/café "[];$\\note\nname.md\n', session_id='x\n\n'),
         path='/work/references/café "[];$\\note\nname.md', session="x"),
    read("read-absent", event(), missing="self-learn"),
    read("read-failure", event(), path=READ_PATH, child_exit=9, child_output=b"ignored"),
    read("read-slow", event(), path=READ_PATH, slow=True),
]
NATIVE_PATH = r"C:\work\references\nested\guide.md"
BACKSLASH = read("read-native-path", event(NATIVE_PATH), path=NATIVE_PATH if WINDOWS else None)
LINUX_DEPS = [
    status("status-no-jq", missing="jq", stdout=DEGRADED + "jq is not on PATH\n"),
    status("status-no-timeout", missing="timeout", stdout=DEGRADED + "timeout is not on PATH\n"),
    read("read-no-jq", event(), missing="jq"),
    read("read-no-timeout", event(), missing="timeout"),
    read("read-no-cat", event(), missing="cat"),
]

STUB = """\
import json
import os
from pathlib import Path
import sys
import time


def entrypoint():
    stdin = sys.stdin.buffer.read()
    with open(os.environ["HOOK_LOG"], "a", encoding="utf-8") as handle:
        print(json.dumps([sys.argv[1:], stdin.hex()]), file=handle)
    sys.stdout.buffer.write(bytes.fromhex(os.environ["HOOK_OUTPUT"]))
    sys.stderr.buffer.write(b"ignored child stderr\\n")
    if os.environ["HOOK_SLOW"] == "1":
        time.sleep(7)
    Path(os.environ["HOOK_DONE"]).touch()
    return int(os.environ["HOOK_EXIT"])


if __name__ == "__main__":
    raise SystemExit(entrypoint())
"""


def installed(name):
    path = Path(sys.executable).parent / (name + (".exe" if WINDOWS else ""))
    assert path.is_file(), f"uv did not install {name}: {path}"
    return path


def fixture_env(tmp_path, case):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.jsonl"
    done = tmp_path / "child-done"
    env = {
        "PATH": str(bindir),
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "profile"),
        "SELF_LEARN_HOME": str(tmp_path / "ledger"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "HOOK_LOG": str(log),
        "HOOK_DONE": str(done),
        "HOOK_OUTPUT": case.child_output.hex(),
        "HOOK_EXIT": str(case.child_exit),
        "HOOK_SLOW": str(int(case.slow)),
    }
    if WINDOWS:
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            if name in os.environ:
                env[name] = os.environ[name]
        env["PATHEXT"] = ".EXE"
        # Use a native uv launcher with a fixture module in front of the real
        # package. Fallback imports from the package are for hook_entry only.
        stub = tmp_path / "fixture" / "self_learn"
        stub.mkdir(parents=True)
        (stub / "__init__.py").write_text(
            f"__path__.append({str(Path(self_learn.__file__).parent)!r})\n", encoding="utf-8",
        )
        (stub / "cli.py").write_text(STUB, encoding="utf-8")
        env["PYTHONPATH"] = str(stub.parent)
        if case.missing != "self-learn":
            shutil.copyfile(installed("self-learn"), bindir / "self-learn.exe")
    else:
        for name in ("jq", "timeout", "cat"):
            if name != case.missing:
                program = shutil.which(name)
                assert program, f"required differential harness binary missing: {name}"
                (bindir / name).symlink_to(program)
        if case.missing != "self-learn":
            stub = bindir / "self-learn"
            stub.write_text(f"#!{sys.executable}\n" + STUB, encoding="utf-8")
            stub.chmod(0o755)
    return env, log, done


def observe(argv, tmp_path, env, log, done, case):
    result = subprocess.run(argv, input=case.stdin, capture_output=True, env=env,
                            cwd=tmp_path, timeout=12)
    invocations = []
    if log.exists():
        invocations = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        log.unlink()
    completed = done.exists()
    if completed:
        done.unlink()
    return result.stdout, result.returncode, invocations, completed


@pytest.mark.skipif(WINDOWS, reason="Bash differential runs on POSIX")
@pytest.mark.parametrize("case", [*CASES, BACKSLASH, *LINUX_DEPS], ids=lambda case: case.name)
def test_bash_differential(tmp_path, case):
    bash = shutil.which("bash")
    if not bash or not shutil.which("jq"):
        pytest.skip("Bash differential requires bash and jq")
    env, log, done = fixture_env(tmp_path, case)
    oracle = observe([bash, str(HOOKS / BASH_HOOKS[case.command])], tmp_path, env, log, done, case)
    assert oracle == case.expected()
    assert observe([str(installed("self-learn-hook")), case.command],
                   tmp_path, env, log, done, case) == oracle


@pytest.mark.skipif(not WINDOWS, reason="native Windows console executable")
@pytest.mark.parametrize("case", [*CASES, BACKSLASH], ids=lambda case: case.name)
def test_windows_console_hook(tmp_path, case):
    env, log, done = fixture_env(tmp_path, case)
    assert observe([str(installed("self-learn-hook")), case.command],
                   tmp_path, env, log, done, case) == case.expected()
