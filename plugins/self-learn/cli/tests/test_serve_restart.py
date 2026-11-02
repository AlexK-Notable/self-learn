"""Explicit restarts are cache-only and are consumed at scheduler boundaries."""
import json
import os
import threading
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
                       "result_path": str(cache / "serve.restart-result")}
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
        result = json.loads((cache / "serve.restart-result").read_text())
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
    result = json.loads((cache / "serve.restart-result").read_text())
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
    result = json.loads((cache / "serve.restart-result").read_text())
    assert result["status"] == "refused" and "Malformed restart request" in result["error"]
    assert not (cache / "serve.restart").exists()
