"""S-165. Observe the process facade across real pipes and process groups."""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

if sys.platform == "linux":
    from self_learn import worker

from self_learn.primitives import procs


windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows process contract")
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


@linux
def test_windows_import_and_first_operation(tmp_path):
    # Select the native backend in a Linux interpreter: no Windows imports or launches.
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


def _assert_no_pipe_threads():
    assert not [t.name for t in threading.enumerate() if t.name.startswith("bounded-")]


def test_argument_stdin_encoding_exit_matrix(tmp_path):
    args = ["", 'a"b', "two words", "trailing slash \\", 'slashes\\\\"quote', "雪⛄", "& whoami"]
    argv = _python("""
        import json, os, sys
        os.write(1, sys.stdin.buffer.read())
        os.write(2, json.dumps([sys.argv[1:], os.getcwd(), os.environ['PROBE']]).encode())
        sys.exit(7)
    """, *args)
    opts = dict(cwd=str(tmp_path), env={**os.environ, "PROBE": "déjà"}, timeout=8)
    payload = bytes(range(256)) * 1024
    done = procs.run_bounded(tuple(argv), input=payload, **opts)
    assert (done.args, done.returncode, done.stdout) == (argv, 7, payload)
    assert json.loads(done.stderr) == [args, str(tmp_path), "déjà"]
    with pytest.raises(subprocess.CalledProcessError) as caught:
        procs.run_bounded(argv, input="雪\r\nline", check=True, **opts)
    assert (caught.value.cmd, caught.value.returncode, caught.value.stdout) == (argv, 7, "雪\nline")
    assert json.loads(caught.value.stderr) == [args, str(tmp_path), "déjà"]
    _assert_no_pipe_threads()


def test_invalid_cap_never_spawns(tmp_path):
    marker = tmp_path / "launched"
    argv = _python("from pathlib import Path; import sys; Path(sys.argv[1]).touch()", marker)
    procs.run_bounded(argv, timeout=5, binary=True, max_output_bytes=1, check=True)
    assert marker.is_file()
    marker.unlink()
    for opts in (dict(binary=True, max_output_bytes=0), dict(max_output_bytes=1),
                 dict(binary=True, input=b"", max_output_bytes=1), dict(binary=True, input="x")):
        with pytest.raises(ValueError):
            procs.run_bounded(argv, timeout=5, **opts)
        assert not marker.exists()


def test_combined_cap_interleaved_n_and_n_plus_one(tmp_path):
    ready = tmp_path / "ready"
    argv = _python("""
        import os, sys, time
        from pathlib import Path
        for i in range(8):
            os.write(1, b"A" * 8192)
            os.write(2, b"B" * 8192)
        Path(sys.argv[1]).touch()
        if sys.argv[2] == "extra":
            os.write(2, b"!")
            time.sleep(15)
    """, ready)
    n = 16 * 8192
    opts = dict(binary=True, max_output_bytes=n, timeout=5)
    done = procs.run_bounded([*argv, "exact"], **opts)
    assert ready.is_file()
    assert (done.stdout, done.stderr, done.returncode) == (b"A" * (n // 2), b"B" * (n // 2), 0)
    ready.unlink()
    with pytest.raises(procs.OutputLimitExceeded, match=f"^child output exceeded {n} bytes$"):
        procs.run_bounded([*argv, "extra"], **opts)
    assert ready.is_file()
    _assert_no_pipe_threads()


@windows
def test_inherited_stdin_and_command_timeout_fields(tmp_path):
    child = _python("import sys; print(sys.stdin.buffer.read().hex())")
    launcher = _python("""
        import json, sys
        from self_learn.primitives import procs
        child = sys.argv[1:]
        print(json.dumps([procs.run_bounded(child, timeout=5).stdout,
                          procs.run_command(child, timeout=5).stdout]))
    """, *child)
    nonce = bytes.fromhex(uuid4().hex)
    result = subprocess.run(launcher, input=nonce, capture_output=True, timeout=15, check=True)
    assert json.loads(result.stdout) == ["\n", nonce.hex() + "\n"]

    ready = tmp_path / "ready"
    slow = _python("""
        import os, sys, time
        from pathlib import Path
        os.write(1, b"started")
        os.write(2, b"waiting")
        Path(sys.argv[1]).touch()
        time.sleep(20)
    """, ready)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        procs.run_command(slow, timeout=2)
    assert ready.is_file() and type(caught.value) is subprocess.TimeoutExpired
    assert (caught.value.cmd, caught.value.timeout, caught.value.output, caught.value.stderr) == (
        slow, 2, b"started", b"waiting")
    _assert_no_pipe_threads()


@windows
def test_git_text_and_byte_exact_output(tmp_path):
    config = tmp_path / "config"
    config.write_bytes(b"[probe]\nvalue = " + "雪".encode() + b"\xff\n")
    argv = ["git", "config", "--file", str(config), "--get", "probe.value"]
    assert procs.run_bounded(argv, binary=True, timeout=5, check=True).stdout.rstrip(b"\r\n") == "雪".encode() + b"\xff"
    for done in (procs.run_command(argv, timeout=5), procs.run_bounded(argv, timeout=5)):
        assert (done.args, done.stdout, done.stderr, done.returncode) == (argv, "雪\ufffd\n", "", 0)
    _assert_no_pipe_threads()


@windows
def test_closed_pipes_live_leader(tmp_path, monkeypatch):
    import win32event
    import win32job
    # Observe the EOFs at the deadline, before termination can close a pipe.
    terminate = win32job.TerminateJobObject
    at_deadline = []
    def observe(*args):
        at_deadline.append([t.name for t in threading.enumerate() if t.name.startswith("bounded-")])
        return terminate(*args)
    monkeypatch.setattr(win32job, "TerminateJobObject", observe)
    ready = tmp_path / "ready"
    wait = win32event.WaitForSingleObject
    waits = []
    def observe_wait(handle, millis):
        if ready.exists() and not at_deadline:
            waits.append(millis)
        return wait(handle, millis)
    monkeypatch.setattr(win32event, "WaitForSingleObject", observe_wait)
    argv = _python("""
        import os, sys, time
        from pathlib import Path
        time.sleep(.7)
        Path(sys.argv[1]).write_text(str(os.getpid()))
        os.close(1)
        os.close(2)
        time.sleep(15)
    """, ready)
    # A Windows venv's python.exe is a redirector that waits with its own
    # copies of both writers. Run the same interpreter directly for real EOF.
    argv[0] = sys._base_executable
    with pytest.raises(procs.BoundedTimeout) as caught:
        procs.run_bounded(argv, binary=True, max_output_bytes=1, timeout=2)
    exc = caught.value
    assert (exc.cmd, exc.timeout, exc.output, exc.stderr) == (argv, 2, None, None)
    assert at_deadline == [[]]
    assert len(waits) == 1 and 0 < waits[0] < 1500
    pid = int(ready.read_text())
    _wait_for(lambda: not procs.pid_alive(pid))
    _assert_no_pipe_threads()


# A signed beat identifies the writing process even if a pid gets reused.
_BEATS = """
    import os, sys, time
    from pathlib import Path
    path, token, leader, mode = sys.argv[1:]
    with open(path, "ab", buffering=0) as beats:
        for i in range(800):
            beats.write(f"{token} {os.getpid()} {i}\\n".encode())
            if i == 1:
                Path(path + ".ready").touch()
            if mode in ("timeout", "overflow") and not Path(path + ".exited").exists():
                from self_learn.primitives.procs import pid_alive
                if not pid_alive(int(leader)):
                    Path(path + ".exited").touch()
                    if mode == "overflow":
                        os.write(2, b"!!")
            if Path(path + ".stop").exists():
                break
            time.sleep(.025)
"""


@windows
@pytest.mark.parametrize("mode", ["timeout", "overflow", "success"])
def test_job_owns_grandchild_only(tmp_path, monkeypatch, mode):
    import win32process

    # The Windows venv redirector and the Python payload have different PIDs.
    # Give the heartbeat process the kernel PID returned for the job leader.
    leader_pid = tmp_path / "leader-pid"
    create_process = win32process.CreateProcess
    def record_leader(*args):
        result = create_process(*args)
        leader_pid.write_text(str(result[2]))
        return result
    monkeypatch.setattr(win32process, "CreateProcess", record_leader)
    peer_file, owned_file = tmp_path / "peer", tmp_path / "owned"
    peer_token, owned_token = uuid4().hex, uuid4().hex
    peer = subprocess.Popen(_python(_BEATS, peer_file, peer_token, 0, "peer"))
    try:
        _wait_for(lambda: (tmp_path / "peer.ready").exists())
        before = peer_file.read_bytes().splitlines()
        leader = _python("""
            import os, subprocess, sys, time
            from pathlib import Path
            mode, ready, leader_pid, *cmd = sys.argv[1:]
            streams = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) if mode == "success" else dict(close_fds=False)
            subprocess.Popen([*cmd, Path(leader_pid).read_text(), mode], **streams)
            while not Path(ready).exists():
                time.sleep(.025)
            sys.exit(7)
        """, mode, tmp_path / "owned.ready", leader_pid, *_python(_BEATS, owned_file, owned_token))
        opts = dict(binary=True, max_output_bytes=1, timeout=3)
        if mode == "success":
            done = procs.run_bounded(leader, **opts)
            assert (done.returncode, done.stdout, done.stderr) == (7, b"", b"")
        else:
            error = procs.BoundedTimeout if mode == "timeout" else procs.OutputLimitExceeded
            with pytest.raises(error):
                procs.run_bounded(leader, **opts)
            assert (tmp_path / "owned.exited").is_file()
        assert (tmp_path / "owned.ready").is_file()
        first = owned_file.read_bytes().splitlines()[0].split()
        pid = int(first[1])
        _wait_for(lambda: not procs.pid_alive(pid))
        stopped = owned_file.read_bytes()
        assert len(stopped.splitlines()) >= 2
        assert all(line.startswith(f"{owned_token} {pid} ".encode()) for line in stopped.splitlines())
        after = peer_file.read_bytes().splitlines()
        _wait_for(lambda: len(peer_file.read_bytes().splitlines()) >= len(after) + 3)
        assert len(after) > len(before) >= 2
        assert all(line.split()[0] == peer_token.encode() for line in peer_file.read_bytes().splitlines())
        assert owned_file.read_bytes() == stopped
        _assert_no_pipe_threads()
    finally:
        (tmp_path / "peer.stop").touch()
        (tmp_path / "owned.stop").touch()
        peer.wait(timeout=5)


@windows
@pytest.mark.parametrize("fail_at", ["assign", "resume"])
def test_job_launch_failure_never_runs_payload(tmp_path, monkeypatch, fail_at):
    import win32job
    import win32process

    marker = tmp_path / "ready"
    argv = _python("from pathlib import Path; import sys; Path(sys.argv[1]).touch()", marker)
    procs.run_bounded(argv, timeout=5, check=True)
    assert marker.is_file()
    marker.unlink()

    events = []
    created_handles = []
    pids = []
    real_create = win32process.CreateProcess
    real_assign = win32job.AssignProcessToJobObject
    def create(*args):
        assert args[5] & win32process.CREATE_SUSPENDED
        created = real_create(*args)
        created_handles.extend(created[:2])
        pids.append(created[2])
        events.append("create")
        return created
    def assign(*args):
        events.append("assign")
        if fail_at == "assign":
            raise OSError("injected assign failure")
        return real_assign(*args)
    def resume(*args):
        events.append("resume")
        raise OSError("injected resume failure")

    terminate_process = Mock(wraps=win32process.TerminateProcess)
    terminate_job = Mock(wraps=win32job.TerminateJobObject)
    monkeypatch.setattr(win32process, "TerminateProcess", terminate_process)
    monkeypatch.setattr(win32job, "TerminateJobObject", terminate_job)
    monkeypatch.setattr(win32process, "CreateProcess", create)
    monkeypatch.setattr(win32job, "AssignProcessToJobObject", assign)
    monkeypatch.setattr(win32process, "ResumeThread", resume)
    with pytest.raises(OSError, match=f"injected {fail_at} failure"):
        procs.run_bounded(argv, timeout=5)
    assert events == (["create", "assign"] if fail_at == "assign" else ["create", "assign", "resume"])
    assert (terminate_process.call_count, terminate_job.call_count) == (
        (1, 0) if fail_at == "assign" else (0, 1))
    assert len(pids) == 1 and not procs.pid_alive(pids[0])
    assert all(int(h) == 0 for h in created_handles)
    assert not marker.exists()
    _assert_no_pipe_threads()


@windows
def test_pid_probe_alive_then_reaped(tmp_path, monkeypatch):
    import pywintypes
    import win32api
    import win32con
    import win32event
    import winerror

    request, reply = tmp_path / "request", tmp_path / "reply"
    peer = subprocess.Popen(_python("""
        import sys, time
        from pathlib import Path
        request, reply = map(Path, sys.argv[1:])
        for i in range(800):
            if request.exists():
                message = request.read_bytes()
                if message == b"stop":
                    break
                reply.write_bytes(message)
            time.sleep(.025)
    """, request, reply))
    def challenge():
        nonce = uuid4().bytes
        request.write_bytes(nonce)
        _wait_for(lambda: reply.exists() and reply.read_bytes() == nonce)
    try:
        challenge()
        real_open = win32api.OpenProcess
        with monkeypatch.context() as patch:
            observed = Mock(wraps=real_open)
            patch.setattr(win32api, "OpenProcess", observed)
            assert procs.pid_alive(peer.pid)
            observed.assert_called_once_with(win32con.SYNCHRONIZE, False, peer.pid)
            for code, expected in [(winerror.ERROR_ACCESS_DENIED, True),
                                   (winerror.ERROR_INVALID_PARAMETER, False),
                                   (winerror.ERROR_INVALID_HANDLE, None)]:
                observed.side_effect = pywintypes.error(code, "OpenProcess", "injected")
                if expected is None:
                    with pytest.raises(OSError) as caught:
                        procs.pid_alive(peer.pid)
                    assert caught.value.winerror == code
                    assert caught.value.__cause__ is observed.side_effect
                else:
                    assert procs.pid_alive(peer.pid) is expected
            observed.reset_mock()
            assert not procs.pid_alive(0) and not procs.pid_alive(-1)
            observed.assert_not_called()
        with monkeypatch.context() as patch:
            # A wait failure must propagate and the opened handle must close.
            waiting = Mock(side_effect=pywintypes.error(winerror.ERROR_INVALID_HANDLE, "Wait", "injected"))
            patch.setattr(win32event, "WaitForSingleObject", waiting)
            with pytest.raises(OSError) as caught:
                procs.pid_alive(peer.pid)
            assert caught.value.winerror == winerror.ERROR_INVALID_HANDLE
            assert caught.value.__cause__ is waiting.side_effect
            handle, millis = waiting.call_args.args
            assert millis == 0 and int(handle) == 0
        challenge()
    finally:
        request.write_bytes(b"stop")
        peer.wait(timeout=5)
    assert not procs.pid_alive(peer.pid)


@windows
def test_only_child_pipe_ends_inherit_and_all_handles_close(monkeypatch):
    import pywintypes
    import win32api
    import win32job
    import win32pipe
    import win32process
    import winerror

    jobs, pipes, processes = [], [], []
    create_job = win32job.CreateJobObject
    create_pipe = win32pipe.CreatePipe
    create_process = win32process.CreateProcess
    def job(*args):
        handle = create_job(*args)
        jobs.append(handle)
        return handle
    def pipe(*args):
        pair = create_pipe(*args)
        pipes.extend(pair)
        return pair
    def process(*args):
        startup = args[-1]
        child_handles = {int(h) for h in (startup.hStdInput, startup.hStdOutput, startup.hStdError)}
        inheritable = {int(h) for h in [*pipes, *jobs] if os.get_handle_inheritable(int(h))}
        assert inheritable == child_handles
        limits = win32job.QueryInformationJobObject(jobs[0], win32job.JobObjectExtendedLimitInformation)
        assert limits["BasicLimitInformation"]["LimitFlags"] & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        result = create_process(*args)
        processes.extend(result[:2])
        return result
    monkeypatch.setattr(win32job, "CreateJobObject", job)
    monkeypatch.setattr(win32pipe, "CreatePipe", pipe)
    monkeypatch.setattr(win32process, "CreateProcess", process)
    done = procs.run_bounded(_python("import sys; print(sys.stdin.read())"), input="pipe", timeout=5)
    assert done.stdout == "pipe\n"
    assert (len(jobs), len(pipes), len(processes)) == (1, 6, 2)
    # Retain the wrappers so a missing explicit close cannot pass through GC.
    for handle in [*jobs, *pipes, *processes]:
        with pytest.raises(pywintypes.error) as caught:
            win32api.GetHandleInformation(handle)
        assert caught.value.winerror == winerror.ERROR_INVALID_HANDLE


@windows
def test_launcher_death_closes_job(tmp_path):
    beat = tmp_path / "beat"
    token = uuid4().hex
    launcher_pid = tmp_path / "launcher"
    launcher = subprocess.Popen(_python("""
        import os, sys
        from pathlib import Path
        from self_learn.primitives import procs
        Path(sys.argv[1]).write_text(str(os.getpid()))
        procs.run_bounded(sys.argv[2:], timeout=30)
    """, launcher_pid, *_python(_BEATS, beat, token, 0, "peer")))
    try:
        _wait_for(lambda: (tmp_path / "beat.ready").is_file())
        first = beat.read_bytes().splitlines()[0].split()
        assert first[0] == token.encode() and int(first[2]) == 0
        pid = int(first[1])
        os.kill(int(launcher_pid.read_text()), signal.SIGTERM)
        launcher.wait(timeout=5)
        _wait_for(lambda: not procs.pid_alive(pid))
        stopped = beat.read_bytes()
        assert len(stopped.splitlines()) >= 2
        time.sleep(.1)
        assert beat.read_bytes() == stopped
    finally:
        (tmp_path / "beat.stop").touch()
        launcher.wait(timeout=6)


@windows
def test_both_readers_join_before_return(monkeypatch):
    # Make worker completion and thread exit observably different events.
    real_run = threading.Thread.run
    readers = []
    def slow_exit(thread):
        real_run(thread)
        if thread.name in ("bounded-stdout", "bounded-stderr"):
            readers.append(thread)
            time.sleep(.25)
    monkeypatch.setattr(threading.Thread, "run", slow_exit)
    done = procs.run_bounded(_python("import sys; print('out'); print('err', file=sys.stderr)"), timeout=5)
    assert (done.stdout, done.stderr) == ("out\n", "err\n")
    assert {t.name for t in readers} == {"bounded-stdout", "bounded-stderr"}
    assert all(not t.is_alive() for t in readers)


@windows
@pytest.mark.parametrize("failure", ["cwd", "image"])
def test_create_process_error_releases_handles(tmp_path, monkeypatch, failure):
    import pywintypes
    import win32file
    import win32job
    import win32pipe
    import win32process
    import winerror

    handles = []
    def track(api, name):
        real = getattr(api, name)
        def wrapped(*args):
            result = real(*args)
            handles.extend(result if isinstance(result, tuple) else (result,))
            return result
        monkeypatch.setattr(api, name, wrapped)
    track(win32job, "CreateJobObject")
    track(win32file, "CreateFile")
    track(win32pipe, "CreatePipe")
    create = Mock(wraps=win32process.CreateProcess)
    monkeypatch.setattr(win32process, "CreateProcess", create)
    cwd = tmp_path
    if failure == "image":
        fake = tmp_path / "invalid.exe"
        fake.write_text("plain text")
        argv = [str(fake)]
        codes = {winerror.ERROR_BAD_EXE_FORMAT}
    else:
        argv = _python("pass")
        cwd = tmp_path / "missing"
        codes = {winerror.ERROR_PATH_NOT_FOUND, winerror.ERROR_FILE_NOT_FOUND, winerror.ERROR_DIRECTORY}
    with pytest.raises(OSError) as caught:
        procs.run_bounded(argv, cwd=str(cwd), timeout=5)
    create.assert_called_once()
    err = caught.value
    assert type(err) is not pywintypes.error
    assert err.filename == argv[0] and err.strerror and err.errno
    assert err.winerror in codes
    assert isinstance(err.__cause__, pywintypes.error)
    assert err.__cause__.funcname == "CreateProcess" and err.__cause__.winerror == err.winerror
    assert len(handles) == 6 and all(int(h) == 0 for h in handles)
    _assert_no_pipe_threads()


@windows
def test_resolution_uses_child_path_and_cwd(tmp_path):
    folder = tmp_path / "tools"
    folder.mkdir()
    exe = folder / "lane-interpreter.exe"
    shutil.copyfile(sys._base_executable, exe)
    def invoke(program, env):
        return procs.run_bounded([program, "--version"], binary=True,
                                 env=env, cwd=str(tmp_path), timeout=5, check=True).stdout
    expected = invoke(sys.executable, None)
    assert expected.startswith(b"Python 3.")
    # Keep the base interpreter's DLL discoverable beside the renamed executable.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PYTHONHOME"] = sys.base_prefix
    search = os.pathsep.join((str(folder), sys.base_prefix))
    assert invoke(exe.stem, {**env, "Path": search}) == expected
    assert invoke(str(Path("tools") / exe.name), {**env, "Path": sys.base_prefix}) == expected
    with pytest.raises(FileNotFoundError) as caught:
        invoke(exe.stem, {**env, "Path": str(tmp_path)})
    assert caught.value.filename == exe.stem and caught.value.winerror == 2
    assert caught.value.__cause__.winerror == 2


@windows
@pytest.mark.parametrize("suffix", [".cmd", ".bat"])
def test_batch_shim_refusal_names_target(tmp_path, suffix):
    import winerror

    shim = tmp_path / ("lane-shim" + suffix)
    marker = tmp_path / "ran"
    shim.write_text('@echo ran > "%~dp0ran"\n', encoding="ascii")
    with pytest.raises(OSError) as caught:
        procs.run_bounded([str(shim)], timeout=5)
    assert caught.value.winerror == winerror.ERROR_BAD_EXE_FORMAT
    assert caught.value.__cause__.winerror == caught.value.winerror
    assert str(shim) in str(caught.value) and "shell" in caught.value.strerror
    assert not marker.exists()


@windows
@pytest.mark.parametrize("entry", ["run_bounded", "run_command"])
def test_non_git_text_requires_utf8(entry):
    argv = _python("import os; os.write(2, bytes([255]))")
    assert procs.run_bounded(argv, binary=True, timeout=5).stderr == b"\xff"
    with pytest.raises(UnicodeDecodeError) as caught:
        getattr(procs, entry)(argv, timeout=5)
    assert caught.value.encoding == "utf-8" and caught.value.object == b"\xff"


@windows
@pytest.mark.parametrize("operation", ["ReadFile", "WriteFile"])
def test_pipe_api_error_reaches_caller(monkeypatch, operation):
    import pywintypes
    import win32file
    import winerror

    failure = pywintypes.error(winerror.ERROR_INVALID_HANDLE, operation, "injected pipe failure")
    monkeypatch.setattr(win32file, operation, Mock(side_effect=failure))
    with pytest.raises(OSError) as caught:
        procs.run_bounded(_python("import sys; print(sys.stdin.read())"), input="hello", timeout=5)
    assert caught.value.winerror == failure.winerror and caught.value.__cause__ is failure
    _assert_no_pipe_threads()


@windows
def test_stuck_reader_has_bounded_cleanup(monkeypatch):
    import win32api
    import win32con
    import win32process
    from self_learn.primitives import _procs_windows as backend

    real_create = win32process.CreateProcess
    release = threading.Event()
    retained = []
    def create(*args):
        current = win32api.GetCurrentProcess()
        writer = win32api.DuplicateHandle(current, args[-1].hStdOutput, current, 0, False,
                                          win32con.DUPLICATE_SAME_ACCESS)
        # The finite watchdog also frees a broken implementation from CloseHandle.
        def hold():
            release.wait(7)
            win32api.CloseHandle(writer)
        keeper = threading.Thread(target=hold)
        keeper.start()
        retained.append(keeper)
        return real_create(*args)
    monkeypatch.setattr(win32process, "CreateProcess", create)
    monkeypatch.setattr(backend, "_CLEANUP_SECONDS", 1)
    start = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="pipe"):
            procs.run_bounded(_python("print('ready')"), timeout=1)
        assert time.monotonic() - start < 3
        assert len(retained) == 1 and retained[0].is_alive()
        _assert_no_pipe_threads()
    finally:
        release.set()
        for holder in retained:
            holder.join(8)


@windows
def test_interrupt_after_create_reaps_suspended_child(tmp_path, monkeypatch):
    import win32event
    import win32process
    from self_learn.primitives import _procs_windows as backend

    marker = tmp_path / "payload"
    created = []
    real_create = win32process.CreateProcess
    def create(*args):
        result = real_create(*args)
        created.append(result)
        return result
    monkeypatch.setattr(win32process, "CreateProcess", create)
    # Interrupt the first Python line with the native result in local variables.
    def interrupt(frame, event, arg):
        if (frame.f_code is backend._launch.__code__ and event == "line"
                and created and frame.f_locals.get("process") is created[0][0]):
            raise KeyboardInterrupt("after native creation")
        return interrupt
    argv = _python("import sys; from pathlib import Path; Path(sys.argv[1]).touch()", marker)
    previous = sys.gettrace()
    try:
        sys.settrace(interrupt)
        with pytest.raises(KeyboardInterrupt, match="after native creation"):
            procs.run_bounded(argv, timeout=5)
    finally:
        sys.settrace(previous)
    process, thread, pid, _ = created[0]
    try:
        assert not procs.pid_alive(pid)
        assert int(process) == int(thread) == 0 and not marker.exists()
    finally:
        if int(process) and win32event.WaitForSingleObject(process, 0) == win32event.WAIT_TIMEOUT:
            win32process.TerminateProcess(process, 1)


@windows
def test_interrupt_after_thread_start_joins_worker(monkeypatch):
    real_start = threading.Thread.start
    real_run = threading.Thread.run
    started = []
    def run(thread):
        real_run(thread)
        time.sleep(.2)
    def start(thread):
        real_start(thread)
        started.append(thread)
        raise KeyboardInterrupt("after thread start")
    monkeypatch.setattr(threading.Thread, "run", run)
    monkeypatch.setattr(threading.Thread, "start", start)
    with pytest.raises(KeyboardInterrupt, match="after thread start"):
        procs.run_bounded(_python("pass"), timeout=5)
    assert len(started) == 1 and not started[0].is_alive()
