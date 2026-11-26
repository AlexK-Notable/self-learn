"""S-165. Observe the process facade across real pipes and process groups."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from self_learn import worker
from self_learn.primitives import procs


linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux process contract")


def _python(script, *args):
    return [sys.executable, "-u", "-c", textwrap.dedent(script), *map(str, args)]


@linux
def test_command_inherits_stdin_and_preserves_timeout(tmp_path):
    nonce = uuid4().hex
    error_nonce = uuid4().hex
    (tmp_path / "reply").write_text(error_nonce)
    child = _python("""
        import os, sys
        from pathlib import Path
        print(sys.stdin.readline().strip())
        print(Path(os.environ["REPLY_FILE"]).read_text(), file=sys.stderr)
        sys.exit(7)
    """)
    launcher = _python("""
        import json, sys
        from self_learn.primitives import procs
        done = procs.run_command(sys.argv[1:], timeout=5)
        print(json.dumps([done.args, done.returncode, done.stdout, done.stderr]))
    """, *child)
    result = subprocess.run(launcher, input=nonce + "\n", cwd=tmp_path,
                            env={**os.environ, "REPLY_FILE": "reply"},
                            capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(result.stdout) == [child, 7, nonce + "\n", error_nonce + "\n"]

    slow = _python("""
        import sys, time
        print("started", flush=True)
        print("waiting", file=sys.stderr, flush=True)
        time.sleep(20)
    """)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        procs.run_command(slow, timeout=1)
    exc = caught.value
    assert type(exc) is subprocess.TimeoutExpired
    assert (exc.cmd, exc.timeout, exc.output, exc.stderr) == (slow, 1, b"started\n", b"waiting\n")


@linux
def test_bounded_input_env_cwd_and_invalid_cap(tmp_path):
    marker = tmp_path / "launched"
    argv = _python("""
        import os, sys
        from pathlib import Path
        Path(sys.argv[1]).write_bytes(b"launched")
        sys.stdout.buffer.write(sys.stdin.buffer.read())
        sys.stderr.buffer.write(os.fsencode(os.getcwd()) + b":" + os.environb[b"PROBE"])
        sys.exit(7)
    """, marker)
    context = dict(timeout=5, env={**os.environ, "PROBE": "child-value"}, cwd=str(tmp_path))
    errors = [
        (dict(binary=True, input="text", max_output_bytes=0),
         "run_bounded: binary=True requires input to be bytes or None, not str"),
        (dict(binary=True, max_output_bytes=0), None),
        (dict(max_output_bytes=1), None),
        (dict(binary=True, max_output_bytes=1, input=b""), None),
    ]
    for options, message in errors:
        with pytest.raises(ValueError) as caught:
            procs.run_bounded(argv, **context, **options)
        assert str(caught.value) == (message or
            "run_bounded: output limit requires a positive budget, binary=True and no input")
        assert not marker.exists()

    stderr = f"{tmp_path}:child-value"
    for data, expected in [(b"\xff\x00", b"\xff\x00"), (bytearray(b"abc"), b"abc"),
                           ("a\r\nb", "a\nb"), (None, "")]:
        result = procs.run_bounded(tuple(argv), input=data, **context)
        assert (result.args, result.returncode, result.stdout) == (argv, 7, expected)
        assert result.stderr == (os.fsencode(stderr) if isinstance(expected, bytes) else stderr)
        assert marker.read_bytes() == b"launched"
        marker.unlink()
    # Give the launcher actual stdin: inheriting it here would echo the nonce.
    launcher = _python("""
        import json, sys
        from self_learn.primitives import procs
        cwd, *argv = sys.argv[1:]
        result = procs.run_bounded(argv, cwd=cwd, timeout=5)
        print(json.dumps([result.stdout, result.stderr, result.returncode]))
    """, tmp_path, *argv)
    inherited = subprocess.run(launcher, input=uuid4().hex, env=context["env"],
                               capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(inherited.stdout) == ["", stderr, 7]
    assert marker.read_bytes() == b"launched"
    marker.unlink()
    with pytest.raises(subprocess.CalledProcessError) as caught:
        procs.run_bounded(argv, input="payload", check=True, **context)
    exc = caught.value
    assert (exc.cmd, exc.returncode, exc.output, exc.stderr) == (argv, 7, "payload", stderr)
    assert marker.read_bytes() == b"launched"


@linux
def test_combined_cap_n_and_n_plus_one():
    script = """
        import os, sys, time
        os.write(1, b"A" * int(sys.argv[1]))
        os.write(2, b"B" * int(sys.argv[2]))
        time.sleep(int(sys.argv[3]))
    """
    # Each pipe exceeds a single read. Either stream may be readable first.
    n = 70000
    result = procs.run_bounded(_python(script, n, n, 0), binary=True,
                               max_output_bytes=2 * n, timeout=5)
    assert (result.stdout, result.stderr, result.returncode) == (b"A" * n, b"B" * n, 0)
    for out, err, sleep in [(n, n + 1, 0), (1, 1, 20)]:
        limit = out + err - 1
        with pytest.raises(procs.OutputLimitExceeded, match=f"^child output exceeded {limit} bytes$"):
            procs.run_bounded(_python(script, out, err, sleep), binary=True,
                              max_output_bytes=limit, timeout=5)


@contextmanager
def _echo_peer():
    proc = subprocess.Popen(_python("""
        import sys
        for line in sys.stdin:
            print("reply:" + line.strip(), flush=True)
    """), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        yield proc
    finally:
        proc.stdin.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        proc.stdout.close()


def _challenge(proc):
    nonce = uuid4().hex
    proc.stdin.write(nonce + "\n")
    proc.stdin.flush()
    assert select.select([proc.stdout], [], [], 5)[0]
    assert proc.stdout.readline() == f"reply:{nonce}\n"


# The owner waits for two heartbeats before exiting or writing the overflow.
# A successful owner exits with its still-beating child off both capture pipes.
_TREE = """
    import os, sys, time
    from pathlib import Path
    mode, directory = sys.argv[1:]
    root = Path(directory)
    leader = os.getpid()
    if mode != "closed":
        reader, writer = os.pipe()
        if os.fork():
            os.close(writer)
            assert os.read(reader, 1) == b"!"
            if mode != "inherited":
                os.write(1, b"abc")
                os.write(2, b"XY")
            if mode == "overflow":
                time.sleep(30)
            os._exit(7)
        os.close(reader)
    if mode in ("closed", "success"):
        os.close(1)
        os.close(2)
    (root / "identity").write_text(f"{leader} {os.getpid()}")
    with (root / "beats").open("ab", buffering=0) as beats:
        for index in range(1500):
            beats.write(b".")
            if index == 1 and mode != "closed":
                os.write(writer, b"!")
                os.close(writer)
            if mode == "inherited" and os.getppid() != leader:
                (root / "reparented").touch()
            if (root / "stop").exists():
                break
            time.sleep(0.02)
"""


def _dead(pid):
    # A subreaper can still see a killed grandchild in /proc until it waits.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return True
    return stat.rsplit(")", 1)[1].split()[0] == "Z"


def _wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "process observation timed out"
        time.sleep(0.02)


def _identity(directory):
    return tuple(map(int, (directory / "identity").read_text().split()))


def _stopped(directory, mode):
    leader, pid = _identity(directory)
    assert (leader == pid) == (mode == "closed")
    _wait_for(lambda: _dead(leader) and _dead(pid))
    beats = (directory / "beats").read_bytes()
    assert len(beats) >= 2
    time.sleep(0.08)
    assert (directory / "beats").read_bytes() == beats


@linux
def test_deadline_after_eof_and_after_leader_exit(tmp_path):
    with _echo_peer() as unrelated:
        _challenge(unrelated)
        for mode in ("closed", "inherited"):
            directory = tmp_path / mode
            directory.mkdir()
            argv = _python(_TREE, mode, directory)
            try:
                start = time.monotonic()
                with pytest.raises(procs.BoundedTimeout) as caught:
                    procs.run_bounded(argv, timeout=1.5, binary=True, max_output_bytes=10)
                assert 1.4 <= time.monotonic() - start < 8
                assert (caught.value.cmd, caught.value.timeout) == (argv, 1.5)
                if mode == "inherited":
                    assert (directory / "reparented").exists()
                _stopped(directory, mode)
                _challenge(unrelated)
            finally:
                (directory / "stop").touch()


@linux
def test_overflow_kills_owned_descendant_only(tmp_path):
    with _echo_peer() as unrelated:
        _challenge(unrelated)
        for mode, cap in [("overflow", 4), ("success", 6)]:
            directory = tmp_path / mode
            directory.mkdir()
            argv = _python(_TREE, mode, directory)
            args = dict(binary=True, max_output_bytes=cap, timeout=5)
            try:
                if mode == "overflow":
                    with pytest.raises(procs.OutputLimitExceeded, match="^child output exceeded 4 bytes$"):
                        procs.run_bounded(argv, **args)
                    _stopped(directory, mode)
                else:
                    done = procs.run_bounded(argv, **args)
                    assert (done.stdout, done.stderr, done.returncode) == (b"abc", b"XY", 7)
                    beats = directory / "beats"
                    last = beats.stat().st_size
                    _wait_for(lambda: beats.stat().st_size > last)
                _challenge(unrelated)
            finally:
                (directory / "stop").touch()
            _, descendant = _identity(directory)
            _wait_for(lambda: _dead(descendant))


@linux
def test_pid_while_live_and_after_reap(monkeypatch):
    with _echo_peer() as peer:
        _challenge(peer)
        assert worker._pid_alive(peer.pid) is True
        for error, expected, pid in [(PermissionError(), True, -17), (ProcessLookupError(), False, 0),
                                     (ValueError(), False, -3), (OSError("unexpected"), None, 37)]:
            with monkeypatch.context() as patch:
                kill = Mock(side_effect=error)
                patch.setattr(os, "kill", kill)
                if expected is None:
                    with pytest.raises(OSError) as caught:
                        worker._pid_alive(pid)
                    assert caught.value is error
                else:
                    assert worker._pid_alive(pid) is expected
                kill.assert_called_once_with(pid, 0)
        _challenge(peer)
        assert worker._pid_alive(peer.pid) is True
    assert peer.returncode is not None
    assert worker._pid_alive(peer.pid) is False


@linux
def test_timeout_cleanup_fallback_order(monkeypatch):
    argv = _python("print('restored')")
    original = subprocess.TimeoutExpired(argv, 1)
    drain_timeout = subprocess.TimeoutExpired(argv, 5)
    group = ("group", 123, signal.SIGKILL)
    drain = ("communicate", {"timeout": 5})
    start = [("communicate", {"input": None, "timeout": 1}), group]
    unexpected = OSError("drain failed")
    # Each row starts with a fresh child and fresh patches.
    for drains, tail, error in [
        ([None], [drain], None),
        ([unexpected], [drain], unexpected),
        ([drain_timeout, None], [drain, ("kill",), drain], None),
        ([drain_timeout, drain_timeout], [drain, ("kill",), drain], None),
        ([drain_timeout, unexpected], [drain, ("kill",), drain], unexpected),
    ]:
        events = []
        outcomes = iter([original, *drains])

        def communicate(**kwargs):
            events.append(("communicate", kwargs))
            outcome = next(outcomes)
            if outcome is not None:
                raise outcome
            return "", ""

        child = Mock(pid=123, communicate=communicate)
        child.kill.side_effect = lambda: events.append(("kill",))
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", Mock(return_value=child))
            patch.setattr(os, "killpg", lambda pid, sig: events.append(("group", pid, sig)))
            with pytest.raises(type(error) if error else procs.BoundedTimeout) as caught:
                procs.run_bounded(argv, timeout=1)
            if error is not None:
                assert caught.value is error
            else:
                exc = caught.value
                assert type(exc) is procs.BoundedTimeout
                assert (exc.cmd, exc.timeout, exc.output, exc.stderr) == (argv, 1, None, None)
                assert exc.__suppress_context__ and exc.__cause__ is None
            assert events == start + tail
    done = procs.run_bounded(argv, timeout=5)
    assert (done.stdout, done.stderr, done.returncode) == ("restored\n", "", 0)


def test_windows_import_and_first_operation(tmp_path):
    # Native Windows uses its actual selector. Linux exercises the same first-use
    # branch in a fresh interpreter by changing only the facade's OS reference.
    marker = tmp_path / "marker"
    script = """
        import os, subprocess, sys
        from pathlib import Path
        from types import SimpleNamespace
        from self_learn.primitives import procs
        from self_learn import gitops, hosts, ledger, worker

        marker = Path(sys.argv[1])
        names = ("run_bounded", "run_command", "pid_alive")
        assert all(callable(getattr(procs, name)) for name in names)
        assert issubclass(procs.BoundedTimeout, subprocess.TimeoutExpired)
        assert issubclass(procs.OutputLimitExceeded, RuntimeError)
        assert "self_learn.primitives._procs_posix" not in sys.modules
        print("imported", *names, flush=True)
        if os.name != "nt":
            procs.os = SimpleNamespace(name="nt")
        argv = [sys.executable, "-c",
                "import sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(b'child')",
                str(marker)]
        launches = []
        def observe(event, args):
            if event == "subprocess.Popen":
                launches.append(args[0])
            if event == "os.kill":
                raise AssertionError("PID probe reached the OS")
        sys.addaudithook(observe)
        root = marker.parent
        for operation in (lambda: procs.run_bounded(argv, timeout=5),
                          lambda: procs.run_command(argv, timeout=5),
                          lambda: procs.pid_alive(os.getpid()),
                          lambda: worker._pid_alive(os.getpid()),
                          lambda: gitops._git(root, "status"),
                          lambda: gitops._git_nolock(root, "status"),
                          lambda: hosts._is_git_repo(root), lambda: hosts.is_repo_root(root),
                          lambda: ledger.home_state_message("not-a-repo", root),
                          lambda: ledger._git_init(root / "repo")):
            try:
                operation()
            except NotImplementedError:
                pass
            else:
                raise AssertionError("process operation returned on Windows")
            assert not launches and not marker.exists() and not (root / "repo").exists()
        assert "self_learn.primitives._procs_posix" not in sys.modules
        subprocess.run(argv, timeout=5, check=True)
        assert len(launches) == 1 and marker.read_bytes() == b"child"
    """
    done = subprocess.run(_python(script, marker), capture_output=True, text=True, timeout=15)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["imported run_bounded run_command pid_alive"]
    assert marker.read_bytes() == b"child"
