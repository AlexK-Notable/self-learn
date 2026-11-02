"""Explicit restarts are cache-only and are consumed at scheduler boundaries."""
import json
import os
import threading
import subprocess
import sys
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from self_learn import cli, serve, worker


@pytest.fixture
def host(tmp_path, monkeypatch):
    home, cache = tmp_path / "ledger", tmp_path / "cache"
    home.mkdir()
    cache.mkdir()
    (home / "unchanged").write_text("ledger truth")
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv(serve._RESTART_ID_ENV, raising=False)
    monkeypatch.setattr(serve, "_sweep_cache", lambda h: None)
    monkeypatch.setattr(serve, "_new_code_imports", lambda: (True, ""))
    monkeypatch.setattr(serve, "_sync_venv", lambda p: (True, ""))
    monkeypatch.setattr(serve, "_restart_on_new_code", lambda h: False)
    monkeypatch.setattr(serve, "_hold_notice", lambda *a: pytest.fail("request wrote a ledger notice"))
    before = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    yield home, cache
    assert {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()} == before


def test_cli_restart_is_cache_only_and_never_starts_loop(host, monkeypatch, capsys):
    home, _ = host
    monkeypatch.setattr(serve, "run_forever", lambda *a, **k: pytest.fail("started loop"))
    assert cli.main(["serve", "--restart"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    receipt = json.loads(lines[0])
    cache = worker.cache_dir(home)
    request = json.loads((cache / "serve.restart").read_text())
    assert receipt == {"requested": True, "id": request["id"],
                       "result_path": str(cache / "serve.restart-results" / (request["id"] + ".json"))}
    assert type(request["requested_at"]) is float and abs(request["requested_at"] - time.time()) < 5
    assert len(request["id"]) == 32
    assert serve.request_restart(cache)["id"] != request["id"]


def test_request_during_real_tick_waits_for_all_jobs(host, monkeypatch):
    home, cache = host
    events, calls = [], []
    receipt = serve.request_restart(cache)
    monkeypatch.setattr(serve, "_due_or_hold", lambda job, *a: job == "mine")
    watch = serve._CodeWatch(running=None, started_at=42)

    def mine():
        events.append("mine")
        assert serve._jobs_in_flight == 1
        serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
        assert (cache / "serve.restart").exists()
        assert calls == []
        return SimpleNamespace(landed=["fixture"])

    def worker_job():
        events.append("worker")
        assert calls == [] and (cache / "serve.restart").exists()
        return None

    def reexec(argv, env):
        assert serve._jobs_in_flight == 0
        assert events == ["mine", "worker"]
        assert argv == serve._exec_argv()
        assert float(env[serve._STARTED_AT_ENV]) == 42
        calls.append(argv)
        assert not (cache / "serve.restart").exists()
        assert (cache / "serve.restart.claimed").exists()
        assert env[serve._RESTART_ID_ENV] == receipt["id"]
        result = json.loads(Path(receipt["result_path"]).read_text())
        assert result["id"] == receipt["id"] and result["status"] == "restarting"
        assert result["error"] is None and abs(result["at"] - time.time()) < 5
        assert serve.read_heartbeat(cache)["next_job"] == "restarting on request"

    monkeypatch.setenv(serve._STARTED_AT_ENV, "42")
    monkeypatch.setattr(serve, "_run_mine_job", lambda h: mine())
    monkeypatch.setattr(serve, "_run_worker_job", lambda h: worker_job())
    monkeypatch.setattr(serve, "_reexec", reexec)
    # The second tick has no due jobs; a mock exec returns to the old image.
    actual_tick = serve._run_tick
    def tick(*a, **k):
        return actual_tick(*a, **k) if not calls else []
    monkeypatch.setattr(serve, "_run_tick", tick)
    assert serve.run_forever(home, cache_dir=cache, tick_secs=.01, max_ticks=2) == 0
    assert len(calls) == 1
    rows = [json.loads(line) for line in (cache / serve.SERVE_JOURNAL_FILENAME).read_text().splitlines()]
    assert any(row["status"] == "reexec" for row in rows)


@pytest.mark.parametrize("tick_secs", [2, .3])
def test_idle_restart_wakes_within_about_one_second(host, monkeypatch, tick_secs):
    home, cache = host
    class Execed(BaseException):
        pass
    ticks, sent = [], []
    monkeypatch.setattr(serve, "_run_tick", lambda *a, **k: ticks.append(time.monotonic()))
    def reexec(*a):
        assert len(ticks) == 1, "an idle request must not start a new tick first"
        assert time.monotonic() - sent[0] < 1.4
        raise Execed()
    monkeypatch.setattr(serve, "_reexec", reexec)
    def request():
        sent.append(time.monotonic())
        serve.request_restart(cache)
    timer = threading.Timer(.2, request)
    timer.start()
    try:
        with pytest.raises(Execed):
            serve.run_forever(home, cache_dir=cache, tick_secs=tick_secs, max_ticks=2)
    finally:
        timer.join()


@pytest.mark.parametrize("failure", ["sync", "import", "exec"])
def test_refusal_removes_request_and_is_not_retried(host, monkeypatch, failure):
    home, cache = host
    receipt = serve.request_restart(cache)
    watch = serve._CodeWatch(running="old", running_env="old", started_at=42)
    monkeypatch.setattr(serve, "env_fingerprint", lambda: "new")
    monkeypatch.setattr(serve, "_project_root", lambda: home)
    calls = []
    def sync(p):
        calls.append("sync")
        return (False, "fixture sync failed") if failure == "sync" else (True, "")
    def imports():
        calls.append("import")
        return (False, "fixture import failed") if failure == "import" else (True, "")
    def exec_fail(*a):
        calls.append("exec")
        raise OSError("fixture exec failed")
    monkeypatch.setattr(serve, "_sync_venv", sync)
    monkeypatch.setattr(serve, "_new_code_imports", imports)
    monkeypatch.setattr(serve, "_reexec", exec_fail)
    for _ in range(2):
        serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    assert calls == {"sync": ["sync"], "import": ["sync", "import"], "exec": ["sync", "import", "exec"]}[failure]
    result = json.loads(Path(receipt["result_path"]).read_text())
    assert result["id"] == receipt["id"] and result["status"] == "refused"
    assert f"fixture {failure} failed" in result["error"]
    assert not (cache / "serve.restart").exists()


@pytest.mark.parametrize("raw", ['no json', '[]', '{"id": 3}',
    '{"id": "a", "requested_at": NaN}', '{"id": "a", "requested_at": true}'])
def test_malformed_request_is_refused_and_removed(host, monkeypatch, raw):
    home, cache = host
    (cache / "serve.restart").write_text(raw)
    monkeypatch.setattr(serve, "_reexec", lambda *a: pytest.fail("exec on malformed request"))
    serve._consider_restart(home, cache, serve._CodeWatch(running=None, started_at=42), pid=1, tick_secs=60)
    results = list((cache / "serve.restart-results").glob("*.json"))
    assert len(results) == 1
    result = json.loads(results[0].read_text())
    assert result["status"] == "refused" and "Malformed restart request" in result["error"]
    assert not (cache / "serve.restart").exists()


def test_new_request_survives_claim_and_both_images_acknowledge_in_order(host, monkeypatch):
    home, cache = host
    first = serve.request_restart(cache)
    next_requests, execs = [], []
    def imports():
        assert (cache / "serve.restart.claimed").exists()
        if not next_requests:
            next_requests.append(serve.request_restart(cache))
        return True, ""
    def exec_image(argv, env):
        execs.append(env[serve._RESTART_ID_ENV])
    monkeypatch.setattr(serve, "_new_code_imports", imports)
    monkeypatch.setattr(serve, "_reexec", exec_image)
    watch = serve._CodeWatch(running=None, started_at=42)
    serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    second = next_requests[0]
    assert execs == [first["id"]]
    assert json.loads((cache / "serve.restart").read_text())["id"] == second["id"]
    # A returning exec stub cannot claim over the outstanding first image.
    serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    assert execs == [first["id"]]
    monkeypatch.setenv(serve._RESTART_ID_ENV, first["id"])
    serve._recover_restart(cache)
    assert serve._RESTART_ID_ENV not in os.environ
    serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    assert execs == [first["id"], second["id"]]
    monkeypatch.setenv(serve._RESTART_ID_ENV, second["id"])
    serve._recover_restart(cache)
    for receipt in (first, second):
        assert json.loads(Path(receipt["result_path"]).read_text())["status"] == "restarted"
    assert first["result_path"] != second["result_path"]
    assert not (cache / "serve.restart").exists()
    assert not (cache / "serve.restart.claimed").exists()
    # Later automatic execs must not carry a stale request acknowledgement.
    monkeypatch.setenv(serve._RESTART_ID_ENV, first["id"])
    monkeypatch.setattr(serve, "_new_code_imports", lambda: (True, ""))
    passed = []
    monkeypatch.setattr(serve, "_reexec", lambda argv, env: passed.append(env))
    serve._attempt_reexec(home, cache, watch, pid=1, tick_secs=60, current="code",
                          env_now=watch.running_env, moment=time.time())
    assert serve._RESTART_ID_ENV not in passed[0]


@pytest.mark.parametrize(("status", "ack"), [(None, False), ("restarting", False),
    (None, True), ("restarting", True), ("refused", False), ("restarted", False)])
def test_startup_recovers_leftover_claim_before_any_tick(host, monkeypatch, status, ack):
    home, cache = host
    old = serve.request_restart(cache)
    os.rename(cache / "serve.restart", cache / "serve.restart.claimed")
    if status is not None:
        serve._restart_result(cache, old["id"], status, "old refusal" if status == "refused" else None)
    pending = serve.request_restart(cache)
    if ack:
        monkeypatch.setenv(serve._RESTART_ID_ENV, old["id"])
    expected = "restarted" if ack else status if status in ("restarted", "refused") else "refused"
    observed, startup_state = [], []
    def tick(*a, **k):
        observed.append(json.loads(Path(old["result_path"]).read_text()))
        startup_state.append(((cache / "serve.restart.claimed").exists(),
                              serve._RESTART_ID_ENV in os.environ))
        return []
    monkeypatch.setattr(serve, "_run_tick", tick)
    serve.run_forever(home, cache_dir=cache, max_ticks=1)
    # Assert outside the tick: run_forever intentionally contains tick exceptions.
    assert startup_state == [(False, False)]
    assert len(observed) == 1 and observed[0]["status"] == expected
    if not ack and status in (None, "restarting"):
        assert observed[0]["error"] == "the service stopped before taking it"
    assert json.loads((cache / "serve.restart").read_text())["id"] == pending["id"]


def test_result_writer_prunes_only_results_older_than_a_day(host):
    _, cache = host
    old, recent = serve.request_restart(cache), serve.request_restart(cache)
    serve._restart_result(cache, old["id"], "refused", "old")
    serve._restart_result(cache, recent["id"], "refused", "recent")
    old_path, recent_path = Path(old["result_path"]), Path(recent["result_path"])
    os.utime(old_path, (time.time() - 86401, time.time() - 86401))
    unrelated = cache / "keep-me"
    unrelated.write_text("keep")
    os.utime(unrelated, (time.time() - 90000, time.time() - 90000))
    newest = serve.request_restart(cache)
    serve._restart_result(cache, newest["id"], "restarting", None)
    assert not old_path.exists()
    assert recent_path.is_file() and Path(newest["result_path"]).is_file()
    assert unrelated.read_text() == "keep"


def test_explicit_request_reexecs_real_owned_fixture(host, tmp_path):
    """Adapted from gate-r2's fixture: actual exec, same PID, new-image acknowledgement."""
    home, cache = host
    boots, tick = tmp_path / "boots", tmp_path / "tick"
    driver = tmp_path / "fixture-host"
    driver.write_text('''import json,os,time
from pathlib import Path
from self_learn import serve
home,cache=Path(os.environ['SELF_LEARN_HOME']),Path(os.environ['PROBE_CACHE'])
with open(os.environ['PROBE_BOOT'],'a') as f:
    f.write(json.dumps({'pid':os.getpid(),'ack':os.environ.get(serve._RESTART_ID_ENV)})+'\\n')
serve._sweep_cache=lambda h:None
serve._clear_refused_notice=lambda h:None
serve._restart_on_new_code=lambda h:False
serve._new_code_imports=lambda:(True,'')
def tick(*a,**k):
    assert serve._RESTART_ID_ENV not in os.environ
    Path(os.environ['PROBE_TICK']).write_text(str(time.time()))
serve._run_tick=tick
# Witness which image writes each result, without replacing os.execve.
original=serve._restart_result
def result(*args):
    original(*args)
    with open(os.environ['PROBE_WRITES'],'a') as f:
        f.write(json.dumps({'status':args[2], 'boots':len(Path(os.environ['PROBE_BOOT']).read_text().splitlines())})+'\\n')
serve._restart_result=result
raise SystemExit(serve.run_forever(home,cache_dir=cache,tick_secs=.2,max_ticks=8))
''')
    writes = tmp_path / "result-writes"
    env = dict(os.environ, SELF_LEARN_HOME=str(home), XDG_CACHE_HOME=str(tmp_path / "xdg"),
               PROBE_CACHE=str(cache), PROBE_BOOT=str(boots), PROBE_TICK=str(tick), PROBE_WRITES=str(writes))
    with subprocess.Popen([sys.executable, str(driver)], env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as proc:
        deadline = time.monotonic() + 10
        while not tick.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert tick.exists()
        receipt = serve.request_restart(cache)
        _, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, err
        images = [json.loads(line) for line in boots.read_text().splitlines()]
        assert images == [{"pid": proc.pid, "ack": None}, {"pid": proc.pid, "ack": receipt["id"]}], err
        result = json.loads(Path(receipt["result_path"]).read_text())
        assert result["id"] == receipt["id"] and result["status"] == "restarted"
        assert [json.loads(line) for line in writes.read_text().splitlines()] == [
            {"status": "restarting", "boots": 1}, {"status": "restarted", "boots": 2}]
        assert not (cache / "serve.restart.claimed").exists()


def test_refusal_keeps_newer_pending_request_and_its_result(host, monkeypatch):
    home, cache = host
    first = serve.request_restart(cache)
    newer = []
    def imports():
        newer.append(serve.request_restart(cache))
        return False, "fixture refusal"
    monkeypatch.setattr(serve, "_new_code_imports", imports)
    watch = serve._CodeWatch(running=None, started_at=42)
    serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    assert json.loads(Path(first["result_path"]).read_text())["status"] == "refused"
    assert not (cache / "serve.restart.claimed").exists()
    assert json.loads((cache / "serve.restart").read_text())["id"] == newer[0]["id"]
    monkeypatch.setattr(serve, "_new_code_imports", lambda: (False, "second refusal"))
    serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    assert json.loads(Path(newer[0]["result_path"]).read_text())["error"] == "second refusal"
    assert json.loads(Path(first["result_path"]).read_text())["error"] == "fixture refusal"
    assert not (cache / "serve.restart").exists()


def test_unexpected_failure_releases_the_claim(host, monkeypatch):
    """An unexpected error inside the restart check is reported as refused and
    clears the claim, so a later request is still taken. Mutation: drop the
    except branch -> the claim stays and the second request is never taken."""
    home, cache = host
    first = serve.request_restart(cache)
    watch = serve._CodeWatch(running="old", running_env="old", started_at=42)

    def boom():
        raise RuntimeError("fixture surprise")

    monkeypatch.setattr(serve, "_new_code_imports", boom)
    with pytest.raises(RuntimeError):
        serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    result = json.loads(Path(first["result_path"]).read_text())
    assert result["status"] == "refused" and "fixture surprise" in result["error"]
    assert not (cache / "serve.restart.claimed").exists()

    second = serve.request_restart(cache)
    monkeypatch.setattr(serve, "_new_code_imports", lambda: (True, ""))
    taken = []
    monkeypatch.setattr(serve, "_reexec", lambda argv, env: taken.append(env[serve._RESTART_ID_ENV]))
    serve._consider_restart(home, cache, watch, pid=1, tick_secs=60)
    assert taken == [second["id"]]
